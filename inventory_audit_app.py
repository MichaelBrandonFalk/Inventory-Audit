"""Tkinter desktop app for Inventory Audit."""

from __future__ import annotations

from pathlib import Path
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from inventory_audit_core import InventoryAuditError, run_audit, run_s3_audit
from inventory_audit_requirements import APP_NAME, APP_VERSION
from inventory_audit_s3 import scan_inventory_to_csv


APP_TITLE = f"{APP_NAME} v{APP_VERSION}"


class InventoryAuditApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("940x680")

        self.input_path = tk.StringVar()
        self.s3_uri = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(_default_output_dir()))
        self.status_text = tk.StringVar(value="Ready")
        self.running = False
        self.run_started_at: float | None = None
        self.current_phase = "Ready"
        self.heartbeat_after_id: str | None = None

        self._build()

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text=APP_TITLE, font=("Helvetica", 18, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            frame,
            text="Load an S3 inventory CSV/XLSX or scan an S3 path directly, then export CSV and Excel endpoint readiness reports.",
            wraplength=840,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 18))

        self._file_row(frame, 2, "Inventory File", self.input_path, self._browse_input)
        self._entry_row(frame, 3, "S3 Path", self.s3_uri, "Optional direct scan, e.g. s3://bucket/movies/")
        self._file_row(frame, 4, "Output Folder", self.output_dir, self._browse_output, directory=True)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=5, column=0, columnspan=3, sticky="w", pady=(12, 18))
        self.file_button = ttk.Button(button_frame, text="Audit File", command=self._run_file)
        self.file_button.pack(side="left", padx=(0, 10))
        self.inventory_button = ttk.Button(button_frame, text="Create S3 Inventory CSV", command=self._run_s3_inventory)
        self.inventory_button.pack(side="left", padx=(0, 10))
        self.s3_button = ttk.Button(button_frame, text="Audit S3 Path", command=self._run_s3)
        self.s3_button.pack(side="left")

        ttk.Label(frame, textvariable=self.status_text).grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.log = scrolledtext.ScrolledText(frame, height=28, wrap="word")
        self.log.grid(row=7, column=0, columnspan=3, sticky="nsew")
        frame.rowconfigure(7, weight=1)

        self._log("Ready. Choose an inventory export or enter an S3 path to start.")

    def _file_row(self, frame: ttk.Frame, row: int, label: str, variable: tk.StringVar, callback, directory: bool = False) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(12, 12), pady=5)
        button_label = "Browse Folder" if directory else "Browse File"
        ttk.Button(frame, text=button_label, command=callback).grid(row=row, column=2, sticky="ew", pady=5)

    def _entry_row(self, frame: ttk.Frame, row: int, label: str, variable: tk.StringVar, hint: str = "") -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(12, 12), pady=5)
        ttk.Label(frame, text=hint).grid(row=row, column=2, sticky="w", pady=5)

    def _browse_input(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[("Inventory Files", "*.csv *.xlsx *.xlsm"), ("All Files", "*.*")])
        if selected:
            self.input_path.set(selected)
            input_path = Path(selected)
            self._log(f"Selected {input_path}")

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory()
        if selected:
            self.output_dir.set(selected)

    def _run_file(self) -> None:
        input_value = self.input_path.get().strip()
        output_value = self.output_dir.get().strip()
        if not input_value:
            messagebox.showerror(APP_TITLE, "Choose an inventory CSV or XLSX file.")
            return
        if not output_value:
            messagebox.showerror(APP_TITLE, "Choose an output folder.")
            return

        input_path = Path(input_value)
        output_path = Path(output_value) / f"{input_path.stem}_inventory_audit_v{APP_VERSION.replace('.', '_')}"

        self._log(f"Running audit for {input_path} ...")
        try:
            result = run_audit(input_path, output_path)
        except (InventoryAuditError, OSError) as exc:
            self._log(f"Audit failed: {exc}")
            messagebox.showerror(APP_TITLE, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._log(f"Unexpected error: {exc}")
            messagebox.showerror(APP_TITLE, f"Unexpected error: {exc}")
            return

        self._handle_result(result)

    def _run_s3(self) -> None:
        self._start_s3_run(audit_after_inventory=True)

    def _run_s3_inventory(self) -> None:
        self._start_s3_run(audit_after_inventory=False)

    def _start_s3_run(self, audit_after_inventory: bool) -> None:
        if self.running:
            return
        s3_value = self.s3_uri.get().strip()
        output_value = self.output_dir.get().strip()
        if not s3_value:
            messagebox.showerror(APP_TITLE, "Enter an S3 path like s3://bucket/path/.")
            return
        if not output_value:
            messagebox.showerror(APP_TITLE, "Choose an output folder.")
            return

        output_path = Path(output_value) / f"{_safe_output_stem(s3_value)}_inventory_audit_v{APP_VERSION.replace('.', '_')}"
        self._set_running(True)
        mode = "S3 audit" if audit_after_inventory else "S3 inventory export"
        self._record_progress(f"Starting {mode} for {s3_value}")
        self._log("This is read-only. The app will list S3 objects and write local report files only.")

        worker = threading.Thread(
            target=self._run_s3_worker,
            args=(s3_value, output_path, audit_after_inventory),
            daemon=True,
        )
        worker.start()

    def _run_s3_worker(self, s3_uri: str, output_path: Path, audit_after_inventory: bool) -> None:
        try:
            if audit_after_inventory:
                result = run_s3_audit(s3_uri, output_path, progress_callback=self._thread_progress)
            else:
                inventory_csv_path, _inventory_uri, items = scan_inventory_to_csv(
                    s3_uri,
                    output_path,
                    progress_callback=self._thread_progress,
                )
                self.root.after(0, self._handle_inventory_result, inventory_csv_path, len(items))
        except (InventoryAuditError, OSError) as exc:
            self.root.after(0, self._handle_error, str(exc))
        except Exception as exc:  # noqa: BLE001
            self.root.after(0, self._handle_error, f"Unexpected error: {exc}")
        else:
            if audit_after_inventory:
                self.root.after(0, self._handle_result, result)
        finally:
            self.root.after(0, self._set_running, False)

    def _thread_progress(self, message: str) -> None:
        self.root.after(0, self._record_progress, message)

    def _record_progress(self, message: str) -> None:
        self.current_phase = message
        self.status_text.set(message)
        self._log(f"S3: {message}")

    def _handle_result(self, result) -> None:
        if getattr(result, "inventory_csv_path", None):
            self._log(f"Step 1 complete. Raw inventory CSV: {result.inventory_csv_path}")
        self._log(f"Step 2 complete. Wrote audit CSV: {result.csv_path}")
        self._log(f"Step 2 complete. Wrote audit XLSX: {result.xlsx_path}")
        self._log(f"Audited {result.entity_count} row(s) from {result.source_file_count} inventory file(s).")
        self._log(_summarize_endpoint_statuses(result.rows))
        self.status_text.set(f"Complete. Audited {result.entity_count} row(s).")
        messagebox.showinfo(APP_TITLE, f"Wrote audit reports:\n{result.csv_path}\n{result.xlsx_path}")

    def _handle_inventory_result(self, inventory_csv_path: Path, object_count: int) -> None:
        self._log(f"Inventory export complete. Listed {object_count} object(s).")
        self._log(f"Raw inventory CSV: {inventory_csv_path}")
        self.status_text.set(f"Inventory export complete. Listed {object_count} object(s).")
        messagebox.showinfo(APP_TITLE, f"Inventory CSV created:\n{inventory_csv_path}\n\nObjects listed: {object_count}")

    def _handle_error(self, message: str) -> None:
        self._log(f"Audit failed: {message}")
        self.status_text.set("Failed")
        messagebox.showerror(APP_TITLE, message)

    def _set_running(self, running: bool) -> None:
        self.running = running
        if running:
            self.run_started_at = time.monotonic()
            self._schedule_heartbeat()
        else:
            self.run_started_at = None
            if self.heartbeat_after_id is not None:
                self.root.after_cancel(self.heartbeat_after_id)
                self.heartbeat_after_id = None
        state = "disabled" if running else "normal"
        self.file_button.configure(state=state)
        self.inventory_button.configure(state=state)
        self.s3_button.configure(state=state)

    def _schedule_heartbeat(self) -> None:
        if self.heartbeat_after_id is not None:
            self.root.after_cancel(self.heartbeat_after_id)
        self.heartbeat_after_id = self.root.after(30000, self._heartbeat)

    def _heartbeat(self) -> None:
        self.heartbeat_after_id = None
        if not self.running or self.run_started_at is None:
            return
        elapsed_seconds = int(time.monotonic() - self.run_started_at)
        minutes, seconds = divmod(elapsed_seconds, 60)
        self._log(f"Still working ({minutes}m {seconds:02d}s): {self.current_phase}")
        self._schedule_heartbeat()

    def _log(self, message: str) -> None:
        self.log.insert("end", f"{message}\n")
        self.log.see("end")


def _summarize_endpoint_statuses(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "No audit rows were detected."

    endpoints = ["Axinom", "Amazon", "Roku", "Frndly", "T+", "YouTube"]
    lines = ["Endpoint completion summary:"]
    for endpoint in endpoints:
        complete = sum(1 for row in rows if row.get(endpoint) == "complete")
        lines.append(f"- {endpoint}: {complete}/{len(rows)} complete")
    return "\n".join(lines)


def _safe_output_stem(value: str) -> str:
    cleaned = value.replace("s3://", "").strip("/").replace("/", "_")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned).strip("_")
    return cleaned or "s3_inventory"


def _default_output_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.exists() else Path.home()


def main() -> None:
    root = tk.Tk()
    InventoryAuditApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
