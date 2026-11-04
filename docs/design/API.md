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
          calclens_version,ase_version,analysis_revision},
 entries:[{id,filename,sha256,normal_axis,short_distance,note,reviewed,
           review_current,review_stamp,measurements,
           analysis:{report,error}}]}
```

The report is the existing canonical Python report with English messages. The
snapshot may also include `analysis.issues_ko` (same codes, localized messages)
and `analysis.error_ko`. No `cif_base64` appears in snapshots. Begin with the
generated graphene example. `GET /_calclens/health` returns plain `ok`.

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
```

Bulk CIF imports are atomic and limited to 20 × 2 MiB. The normal JSON body cap
is 1 MiB; import/replace actions may use the bounded encoded-project cap.
All operations use existing Project validation, review stamps and cache helpers.
Empty workspaces are not allowed. Removing the selected entry chooses a surviving
entry. A replacement keeps its ID/settings/note, invalidates completion and
pair selections on byte changes, and retains historical review provenance.

`POST /api/v1/project/import` accepts the raw canonical project JSON bytes;
`X-CalcLens-Revision` carries the expected revision. It uses `loads_project`, then
returns a current snapshot. `GET /api/v1/project/export` downloads bytes from
`dumps_project` with the current workspace metadata.

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
ZIPs and Windows packages; no runtime Node or CDN is needed. Keep legacy
Streamlit through an explicit `--legacy-ui` launch option.

Frontend shared types are in `frontend/src/types.ts`. The shell owns App.tsx,
styles.css and API workflows. The molecular viewer owns MolecularViewer.tsx,
viewerGeometry.ts and their tests. Python adapter owns web_api.py and API tests.
