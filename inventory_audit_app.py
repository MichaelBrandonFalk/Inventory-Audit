"""Tkinter desktop app for Inventory Audit."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from inventory_audit_core import InventoryAuditError, run_audit
from inventory_audit_requirements import APP_NAME, APP_VERSION


APP_TITLE = f"{APP_NAME} v{APP_VERSION}"


class InventoryAuditApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("940x680")

        self.input_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "inventory_audit_output"))

        self._build()

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text=APP_TITLE, font=("Helvetica", 18, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            frame,
            text="Load an S3 inventory CSV/XLSX, detect movie/series/season/episode rows, and export endpoint readiness statuses.",
            wraplength=840,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 18))

        self._file_row(frame, 2, "Inventory File", self.input_path, self._browse_input)
        self._file_row(frame, 3, "Output Folder", self.output_dir, self._browse_output, directory=True)

        ttk.Button(frame, text="Run Audit", command=self._run).grid(row=4, column=0, sticky="w", pady=(12, 18))

        self.log = scrolledtext.ScrolledText(frame, height=28, wrap="word")
        self.log.grid(row=5, column=0, columnspan=3, sticky="nsew")
        frame.rowconfigure(5, weight=1)

        self._log("Ready. Choose a Movies or Series inventory export to start.")

    def _file_row(self, frame: ttk.Frame, row: int, label: str, variable: tk.StringVar, callback, directory: bool = False) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(12, 12), pady=5)
        button_label = "Browse Folder" if directory else "Browse File"
        ttk.Button(frame, text=button_label, command=callback).grid(row=row, column=2, sticky="ew", pady=5)

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

    def _run(self) -> None:
        input_value = self.input_path.get().strip()
        output_value = self.output_dir.get().strip()
        if not input_value:
            messagebox.showerror(APP_TITLE, "Choose an inventory CSV or XLSX file.")
            return
        if not output_value:
            messagebox.showerror(APP_TITLE, "Choose an output folder.")
            return

        input_path = Path(input_value)
        output_path = Path(output_value) / f"{input_path.stem}_inventory_audit.csv"

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

        self._log(f"Wrote {result.output_path}")
        self._log(f"Audited {result.entity_count} row(s) from {result.source_file_count} inventory file(s).")
        self._log(_summarize_endpoint_statuses(result.rows))
        messagebox.showinfo(APP_TITLE, f"Wrote audit report:\n{result.output_path}")

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


def main() -> None:
    root = tk.Tk()
    InventoryAuditApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
