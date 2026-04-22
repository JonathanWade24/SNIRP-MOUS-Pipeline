# MOUS Pipeline

Modular analysis pipeline for MOUS oscillatory and traveling-wave analyses.

## Quickstart

```bash
pip install -e .
mous-pipeline run --config configs/pilot_A2002.yaml --subject A2002
```

## Runner options

```bash
# preview selected stages without reading data
mous-pipeline run --config configs/pilot_A2002.yaml --subject A2002 --dry-run

# force recompute even when outputs exist
mous-pipeline run --config configs/pilot_A2002.yaml --subject A2002 --force

# skip report generation stage (m8)
mous-pipeline run --config configs/pilot_A2002.yaml --subject A2002 --skip m8
```

## Download more subjects with Cyberduck

Use Cyberduck CLI (`duck`) to fetch additional subject archives:

```bash
mous-pipeline fetch-subject \
  --subject A2003 \
  --protocol sftp \
  --host your-host.example.org \
  --remote-root /path/to/mous/archives \
  --local-root . \
  --username your_username
```

The command prints an executable `duck` command. Add `--execute` to run it immediately.
