# Windows local folder authorization

Start the application from this branch's root:

```powershell
python scripts/start.py
```

Docker Desktop must be running. Keep the launcher's terminal open while using
local folder selection. The local folder component and native Windows picker
share that interactive console session; they do not create another CMD window.
Docker and other background task subprocesses run without console windows.
No Windows service or login startup entry is installed.

## Choose and authorize

1. Open [File Trace](http://127.0.0.1:3000/select) and choose **Choose local folder**.
   The Windows Shell folder dialog opens in the launcher's interactive session.
2. Select a local directory. Check its displayed path and read-only scope.
   Cancelling the dialog creates no mount, authorization, or scan.
3. Choose **Authorize and start scan**. The component waits for the current
   Worker task to finish, then reconnects API and Worker with that directory
   mounted read-only. Queued tasks remain in PostgreSQL and continue afterward.
   The database, AI service, model cache and frontend are not restarted.
4. Once the directory is accessible, the existing authorization API accepts
   the scan and opens its progress page. Search, source evidence and rescanning
   use the original files, rather than an uploaded snapshot.

The original configured fixture directories remain under **Example/configured
directories**. Explicit mock mode is a labelled simulation and never opens the
real folder component. A failure in API mode never switches to mock data.

## Persistence and recovery

Directory IDs, operations and the generated Compose overlay live under the
Git-ignored and Docker-build-excluded `work/local-folders/` directory. Restart
with the launcher so it loads the same mapping. Choosing the same canonical
directory reuses its mount ID. Only explicitly selected directories are added;
the component does not mount an entire drive to implement browsing.

If an authorized directory is missing at startup, its identity remains saved
but no bind mount is created for that path. It appears unavailable instead of
Docker creating a misleading empty directory. Restore the directory and restart
the launcher to reconnect it.

During preparation, keep the application running; reloading or closing the page
does not cancel the operation. The page resumes polling its saved operation ID.
If preparation is interrupted, the next launch restores the committed directory
configuration before starting services. A failed preparation can be explicitly
retried. An abnormal Worker exit is reported rather than treated as a safe
reconnect: the existing worker has no general recovery for interrupted claims.

A lost scan response does not prove that scanning failed. The UI locks that
submission, checks saved authorizations, and can open the currently indexed
content without automatically submitting the scan again.

Use the launcher for future starts. If running Compose manually after the first
launcher run, include both files:

```powershell
docker compose -f compose.yaml -f work/local-folders/compose.sources.json up -d --no-build
```

## Local component configuration

The component listens only at `127.0.0.1:8765`. Browser requests must come from
the configured local frontend origin and carry a session token after the status
handshake. The component obtains paths from its own native dialog, not from
paths supplied in HTTP requests. Normal scan/search APIs continue to accept
mount IDs and relative paths. Selecting a folder does not bypass Windows file
permissions or grant source write access.

Set `LOCAL_FOLDER_BRIDGE_PORT` in `.env` to change the component port. The
launcher rebuilds the frontend when this setting changes. A different worktree
must use a different port; the launcher refuses to reuse another project's
component. For Vite development, set `VITE_LOCAL_FOLDER_BRIDGE_URL` to the matching
local URL and start the real Docker application with the launcher as well.

The first release covers Windows local directories and read-only PDF indexing,
search, source previews and manual rescans. Folder selection and mount
preparation are asynchronous; they do not share the ordinary API request's
15-second lifetime.

## Upgrading an existing running stack

If the launcher reports `worker_drain_upgrade_required`, the running Worker
predates cooperative exit. It is deliberately not sent an unsupported signal.
Let its current scan and document tasks finish, stop that old stack normally,
and run the launcher again to install the updated Worker. New stacks and later
restarts use cooperative exit automatically. An abnormal Worker exit needs
operator investigation rather than forcing a directory change over an
unresolved claimed task.

## Implementation verification

The 1 November 2026 verification covered 785 passing backend unit/integration
tests (two skipped), 79 frontend tests, 62 Node contract checks, the production
build, and Ruff. Ten isolated browser fixture scenarios covered consent,
preparation, refresh, uncertain scan responses and 375/1024/1440 pixel layouts.

A separate real Docker project verified a Windows source path containing
Chinese characters, spaces and `$`, read-only mounts in both services, Worker
drain with pending work retained, parsing, keyword search, original evidence,
unchanged-version rescanning and restart persistence. Original file hashes
remained unchanged. Windows process tests verified the detached helper's
lifetime and replacement. The real native dialog was automatically exercised
for both confirmation and cancellation using only its own process's controls.
Human usability acceptance remains separate from these automated checks.

Local reports and screenshots are retained under the ignored `work/` directory;
`work/local-folder-verification.json` links the individual reports. Test data
and disposable Docker databases are not part of the application corpus.
