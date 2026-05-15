"""Tkinter desktop app for Inventory Audit."""

from __future__ import annotations

from pathlib import Path
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from inventory_audit_core import InventoryAuditError, run_audit, run_s3_audit
from inventory_audit_requirements import APP_NAME, APP_VERSION


APP_TITLE = f"{APP_NAME} v{APP_VERSION}"


class InventoryAuditApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("940x680")

        self.input_path = tk.StringVar()
        self.s3_uri = tk.StringVar()
        self.aws_profile = tk.StringVar()
        self.aws_region = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "inventory_audit_output"))
        self.running = False

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
        self._entry_row(frame, 4, "AWS Profile", self.aws_profile, "Optional")
        self._entry_row(frame, 5, "AWS Region", self.aws_region, "Optional")
        self._file_row(frame, 6, "Output Folder", self.output_dir, self._browse_output, directory=True)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=7, column=0, columnspan=3, sticky="w", pady=(12, 18))
        self.file_button = ttk.Button(button_frame, text="Audit File", command=self._run_file)
        self.file_button.pack(side="left", padx=(0, 10))
        self.s3_button = ttk.Button(button_frame, text="Audit S3 Path", command=self._run_s3)
        self.s3_button.pack(side="left")

        self.log = scrolledtext.ScrolledText(frame, height=28, wrap="word")
        self.log.grid(row=8, column=0, columnspan=3, sticky="nsew")
        frame.rowconfigure(8, weight=1)

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
            self.output_dir.set(str(input_path.parent))
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
        self._log(f"Scanning {s3_value} ...")

        worker = threading.Thread(
            target=self._run_s3_worker,
            args=(s3_value, output_path, self.aws_profile.get().strip(), self.aws_region.get().strip()),
            daemon=True,
        )
        worker.start()

    def _run_s3_worker(self, s3_uri: str, output_path: Path, profile: str, region: str) -> None:
        try:
            result = run_s3_audit(
                s3_uri,
                output_path,
                profile=profile,
                region=region,
                progress_callback=lambda message: self.root.after(0, self._log, f"S3 scan: {message}"),
            )
        except (InventoryAuditError, OSError) as exc:
            self.root.after(0, self._handle_error, str(exc))
        except Exception as exc:  # noqa: BLE001
            self.root.after(0, self._handle_error, f"Unexpected error: {exc}")
        else:
            self.root.after(0, self._handle_result, result)
        finally:
            self.root.after(0, self._set_running, False)

    def _handle_result(self, result) -> None:
        self._log(f"Wrote {result.csv_path}")
        self._log(f"Wrote {result.xlsx_path}")
        self._log(f"Audited {result.entity_count} row(s) from {result.source_file_count} inventory file(s).")
        self._log(_summarize_endpoint_statuses(result.rows))
        messagebox.showinfo(APP_TITLE, f"Wrote audit reports:\n{result.csv_path}\n{result.xlsx_path}")

    def _handle_error(self, message: str) -> None:
        self._log(f"Audit failed: {message}")
        messagebox.showerror(APP_TITLE, message)

    def _set_running(self, running: bool) -> None:
        self.running = running
        state = "disabled" if running else "normal"
        self.file_button.configure(state=state)
        self.s3_button.configure(state=state)

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


def main() -> None:
    root = tk.Tk()
    InventoryAuditApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
