"""Batch-download playlists from Soulseek through sockseek.exe.

    Playlists/*.txt   input, one playlist per file, lines like "Artist - Title | 4:09"
    output/<name>/    downloads of one playlist, flat, plus sockseek's _index.csv
    work/             generated sockseek list files, rebuilt on every run
    logs/             run_<NNNN>_<time>.log per run, run_seq.txt holds the last number

Modules:
    settings    config.yaml, the folders, the tunable numbers, sockseek.conf lookups
    playlist    playlist files -> entries
    importing   an exported list (m3u/csv/text) -> a playlist file
    index       sockseek's _index.csv: what is already on disk, what failed and why
    runner      building and running the sockseek command
    explain     the extra conditionless search that explains every failure
    quality     the optional ffprobe report
    batch       the run itself
    cli         the engine's command line; run.py is the everyday entry point

Standard library only.
"""
from __future__ import annotations

__version__ = "0.1.0"

from .batch import Batch, Result, RunConfig, next_run_number, run_batch, run_label, SEQ_NAME
from .cli import describe_config, main, options_from_args, parse_args
from .deps import (DEPENDENCIES_NAME, Tool, ensure as ensure_tool,
                   ensure_python_packages, install as install_tool, platform_key,
                   status as tool_status, tools)
from .explain import (Candidate, EXPLAIN_TIMEOUT_S, explain_failure, explain_failures,
                      parse_preview)
from .importing import Imported, Importer, import_file
from .index import (INDEX_NAME, INDEX_OK, REASON_TEXT, Status, failure_dict, failure_rows,
                    find_index_files, format_failure, match_index, playlist_status, read_index,
                    read_index_with_dirs, rows_by_entry)
from .playlist import (Entry, Playlist, Track, build_list_line, convert_playlist, is_generated,
                       parse_duration, parse_line, read_playlist)
from .quality import FFPROBE_FALLBACK, check_downloads, find_ffprobe, probe_file
from .runner import (ERROR, FAILED, NAME_FORMAT, OK, Options, RETRY_PAUSE_S, Sockseek, TIMEOUT,
                     build_command, kill_tree, run_process, run_with_retry)
from .settings import (APP_DIR, CONFIG_NAME, CONFIG_TEMPLATE, CREDENTIAL_KEYS,
                       LEGACY_CONFIG_NAME, LOCAL_CONF_TEMPLATE, PATH_DEFAULTS, PATH_KEYS,
                       SETTINGS, SOCKSEEK_CONF, SOCKSEEK_EFFECTIVE_CONF, SOCKSEEK_LOCAL_CONF,
                       Setting, check_value, config_paths, effective_conf, load_config,
                       merge_conf, missing_credentials, parse_conf, parse_yaml, read_min_bitrate)

__all__ = [name for name in dir() if not name.startswith("_")]
