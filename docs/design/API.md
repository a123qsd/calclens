# Local workspace API v1

Python owns one workspace for each running desktop server. React mirrors its
snapshot. Original CIF bytes remain in Python and appear only in uploaded input
or project downloads. Normal edits never resend the project payload.

The server binds only to `127.0.0.1`. Require the exact Host and Origin and a
process-random `X-CalcLens-Token` for mutations. No CORS; reject chunked or
oversized bodies, unexpected fields, filesystem paths and URLs. Return JSON
errors `{error:{code,message},revision?}` without tracebacks. A stale expected
revision returns HTTP 409 and the UI reloads the current snapshot before retry.

## Snapshots

`GET /api/v1/bootstrap` and `GET /api/v1/workspace` return:

```text
{api_version:1, token, revision, language:'ko'|'en',
 examples:[{name,label_ko,label_en}], limits:{max_files,max_file_bytes,max_pair_selections},
 project:{selected_id,review_focus,filter_mode,progress_filter,
          calclens_version,ase_version,analysis_revision,workspace_state?},
 entries:[{id,filename,sha256,normal_axis,short_distance,note,reviewed,
           review_current,review_stamp,measurements,preparation?,
           analysis:{report,error,auxiliary_structure?}}]}
```

The report is the existing canonical Python report with English messages. The
snapshot may also include `analysis.issues_ko` (same codes, localized messages)
and `analysis.error_ko`. No `cif_base64` appears in snapshots. Begin with the
generated graphene example. `GET /_calclens/health` returns plain `ok`.

`workspace_state` appears only in bootstrap and project preview/import responses;
ordinary workspace reads and action responses omit it. If a source is valid
explicit P1 but its applied analysis axis is unsupported, those restoration
responses may include `auxiliary_structure: {atom_count,elements,positions}`.
This minimal source-derived mapping lets the browser validate saved electronic
files without changing analysis settings or presenting a successful report.
Partially occupied, disordered or unprepared non-P1 inputs do not get this fallback.

## Actions

`POST /api/v1/actions` accepts
`{expected_revision:number,action:{type,...}}` and returns the complete new
snapshot atomically. Supported actions:

```text
load_example {name}
import_cifs {files:[{filename,data_base64}],mode:'replace'|'append'}
replace_source {id,filename,data_base64}
remove_entry {id}
patch_entry {id,normal_axis?,short_distance?,note?}
set_reviewed {id,value:boolean}
patch_workspace {selected_id?,review_focus?,filter_mode?,progress_filter?,language?}
save_measurement {id,selection:{i,j,first_shift:[int,int,int],second_shift:[int,int,int],mode}}
remove_measurement {id,index}
prepare_p1 {id,source_sha256}
```

Bulk CIF imports are atomic and limited to 20 × 2 MiB. The normal JSON body cap
is 1 MiB; import/replace actions may use the bounded encoded-project cap.
All operations use existing Project validation, review stamps and cache helpers.
Empty workspaces are not allowed. Removing the selected entry chooses a surviving
entry. A replacement keeps its ID/settings/note, invalidates completion and
pair selections on byte changes, and retains historical review provenance.

`POST /api/v1/project/import` accepts canonical project JSON or a bounded ZIP
containing only `project.json`;
`X-CalcLens-Revision` carries the expected revision. It uses `loads_project`, then
returns a current snapshot. `GET /api/v1/project/export` downloads bytes from
`dumps_project` with the current workspace metadata.

`POST /api/v1/project/preview` uses the import body/headers but returns a detached
snapshot without replacing the workspace. The browser validates raw electronic
files against its reports before sending the import request.
`POST /api/v1/project/export` accepts `{expected_revision,workspace_state}` with
the normal token and Origin and returns a ZIP without changing the revision.
The opaque workspace extension is bounded, finite JSON. Full data is returned
only for bootstrap and project preview/import, not every edit snapshot.

`POST /api/v1/prepare/p1` accepts `{expected_revision,entry_id}` with token/Origin
and returns source/prepared hashes, CIF preview, site counts, cells, symmetry
metadata, warnings and changes. Applying uses `prepare_p1` and rechecks the source
hash. It retains the original bytes and reproducible transformation metadata.
See [the workspace guide](../WORKSPACE_SAVE.md) for bounds and supported inputs.

## Measurement and reports

`POST /api/v1/measure` accepts
`{expected_revision,entry_id,i,j,first_shift:[int,int,int],second_shift:[int,int,int]}` and returns
the existing `measure_atom_pair` result (`displayed`, `minimum_image`). It is
read-only and does not increment the revision. The server checks
`expected_revision` under the workspace lock before resolving the entry or
measuring it; stale requests return HTTP 409 with the current revision. Require
token and Origin.

```text
GET /api/v1/entries/<id>/report.json?lang=ko|en
GET /api/v1/entries/<id>/report.csv?lang=ko|en
GET /api/v1/comparison.csv?lang=ko|en
```

Use the existing localized_report/report_csv/batch_csv and content-disposition.
Unsupported entries have an error and no numeric report. Workspace changes are
serialized with a lock, and the process has one bounded 40-result analysis cache.
The frontend treats HTTP 409 as a visible multi-tab conflict and refreshes state;
it must not overwrite newer work automatically.

## Offline assets and ownership

Vite builds `frontend/` into `src/slab_preflight/web_assets/`. The Python server
serves only that fixed directory. Static assets are bundled into wheels, source
ZIPs and Windows packages; no runtime Node or CDN is needed. The legacy
Streamlit launch option `--legacy-ui` requires the optional `legacy-ui` dependency
extra or a Windows build made with `--include-legacy-ui`.

Frontend shared types are in `frontend/src/types.ts`. The shell owns App.tsx,
styles.css and API workflows. The molecular viewer owns MolecularViewer.tsx,
viewerGeometry.ts and their tests. Python adapter owns web_api.py and API tests.
