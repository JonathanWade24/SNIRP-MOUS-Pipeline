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

## Download subjects from RDR (Repocli)

1. Install `repocli` from [Donders-Institute/dr-tools releases](https://github.com/Donders-Institute/dr-tools/releases) (e.g. `repocli.x86_64` for Linux).
2. Configure once:

```bash
repocli config
```

At `repo baseurl:` enter `https://webdav.data.ru.nl`, then your RDR **Data access** credentials.

3. Set `rdr.collection_path` in your YAML to the collection folder (e.g. `dccn/DSC_3011020.09_236_v1`), matching the path under WebDAV after `dccn/`.

4. Pull a subject into `data_root`:

```bash
mous-pipeline fetch-rdr --config configs/pilot_A2002.yaml --subject A2002 --execute
```

Or override the collection path:

```bash
mous-pipeline fetch-rdr --subject A2003 --collection-path dccn/DSC_3011020.09_236_v1 --dest . --execute
```

Then run the pipeline as usual (`mous-pipeline run ...`).
