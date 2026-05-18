# Inventory Audit

Inventory Audit v1.2 audits S3 inventories against first-pass endpoint readiness rules.

## What v1.2 Does

- Reads S3 inventory `.csv`, `.xlsx`, or `.xlsm` files with `bucket`, `key`, `size_bytes`, `last_modified`, and `s3_uri` columns.
- Scans S3 paths directly using the same read-only inventory flow as S3 Organizer.
- Writes direct S3 scan raw inventory CSVs before running the audit.
- Defaults report output to the user's `Downloads` folder.
- Detects `Movie`, `Series`, `Season`, and `Episode` rows from S3-style folder paths.
- Splits parent folder names into title and SKU when the folder ends with a UUID or long numeric SKU, such as `county_rescue_2310526531722`.
- Outputs one audit row per movie, series root, season, and episode.
- Tracks `mov`, `vtt`, and `srt` presence for movie and episode rows only.
- Tracks the largest detected image dimension for each supported art field:
  - `ca_16x9`
  - `ca_1x1`
  - `ca_4x3`
  - `ca_2x3`
  - `ca_3x4`
  - `bg_16x9`
  - `bg_2x3`
  - `tt_9x5`
- Marks each endpoint as `complete` or `incomplete`, with endpoint status columns at the far left of the report.
- Writes both `.csv` and Excel `.xlsx` reports.

## Endpoint Rules Included

The art rules are backed into the app from `Streamlined Logic For Art Req in Rally Publishes (9).xlsx`.

The YouTube optional `BG 2:3` requirement is ignored in v1 as requested. Other optional sheet entries are also not treated as required.

Axinom is included as an endpoint, but art rules are empty in v1 because Axinom was not included in the supplied matrix.

Media/caption assumption in v1:

- Movie and episode rows require `.mov` for every endpoint.
- Amazon requires `.srt`.
- Non-Amazon endpoints require `.vtt`.
- Series and season rows only audit art.

## Run From Source

```bash
python3 inventory_audit_app.py
```

CLI mode is also available:

```bash
python3 inventory_audit_core.py /path/to/inventory.csv -o /path/to/audit
```

Direct S3 scan:

```bash
python3 inventory_audit_core.py --s3 s3://bucket/path/ -o /path/to/audit
```

## Install Requirements

CSV support uses only the Python standard library. XLSX input/output requires `openpyxl`. Direct S3 scans require `boto3`.

For direct S3 scans, the app first tries saved S3 Organizer credentials and region settings. If those are not present, it falls back to the normal AWS credential chain on the machine.

```bash
python3 -m pip install -r requirements.txt
```

## Build A macOS App

```bash
./build_inventory_audit_v1_2.sh
```

The build script writes:

```text
dist/Inventory Audit.app
dist/Inventory_Audit_v1_2-macOS-arm64.zip
```

Intel macOS:

```bash
./build_inventory_audit_v1_2_intel.sh
```

Windows builds are handled by GitHub Actions:

```text
.github/workflows/build-windows.yml
```

## S3 Inventory Output

Direct S3 scans are read-only. They list objects and write a raw inventory CSV with:

- `bucket`
- `key`
- `size_bytes`
- `last_modified`
- `s3_uri`

The audit then reads those rows through the same parser used for uploaded CSV/XLSX inventory files.
