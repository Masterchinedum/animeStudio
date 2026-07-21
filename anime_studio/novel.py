"""Long-form novel production with Vertex Gemini and Cloud Storage batches.

The novel is a separate memory bank inside an Anime Studio project.  Planning is a
single Vertex request so the author can approve it.  Prose is submitted through
Vertex Batch Prediction: one JSONL line per chapter, one Markdown file per result.

Batch windows deliberately stay small.  A novel needs the canon emitted by previous
chapters; submitting one hundred chapters from one static prompt is fast but creates
contradictions.  The default is five chapters per Vertex job, then a fresh canon
snapshot feeds the next window.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

from . import store
from .paths import ProjectPaths
from .providers import gcloud_auth
from .providers.base import ProviderError
from .providers.vertex_text import VertexTextProvider


class NovelError(ProviderError):
    """A missing novel prerequisite or a Vertex Batch failure."""


DEFAULT_MAX_BATCH_CHAPTERS = 5
DEFAULT_MAX_OUTPUT_TOKENS = 5200
_CHAPTER_ID = re.compile(r"NOVEL_CHAPTER_ID:\s*(\d+)")
_CANON_TRAILER = re.compile(r"\n?<!--\s*NOVEL_CANON\s*(\{.*?\})\s*-->\s*$", re.DOTALL)


def ensure_workspace(paths: ProjectPaths) -> None:
    for directory in (paths.novel, paths.novel_planning, paths.novel_chapters,
                      paths.novel_batches, paths.novel_canon_updates):
        directory.mkdir(parents=True, exist_ok=True)
    if not paths.novel_state.exists():
        store.save_json(paths.novel_state, {
            "step_1": {"status": "empty", "approved": False},
            "batches": {},
        })


def status(paths: ProjectPaths) -> dict:
    ensure_workspace(paths)
    state = store.load_json(paths.novel_state)
    chapters = sorted(paths.novel_chapters.glob("chapter_*.md"))
    outstanding = [entry for entry in state.get("batches", {}).values()
                   if entry.get("status") in {"submitted", "running"}]
    return {
        "step_1": state.get("step_1", {}),
        "chapters": len(chapters),
        "outstanding": outstanding,
    }


def run_step_1(paths: ProjectPaths, *, force: bool = False) -> dict:
    """Generate the reviewable series foundation before any prose is drafted."""
    ensure_workspace(paths)
    state = store.load_json(paths.novel_state)
    if paths.novel_step1.exists() and not force:
        return {"status": "skipped", "path": paths.novel_step1}
    brief = _required_text(paths.novel_brief, "Novel brief")
    config = _vertex_config(paths, require_bucket=False)
    project = store.load_project(paths)
    provider = VertexTextProvider(project=config["project"], location=config["location"],
                                  model=config["model"])
    response = provider.generate(
        "\n\n".join([
            "You are preparing the approved foundation for a long-form novel.",
            f"Project title: {project.title or project.id}",
            "Read the master brief below and execute Step 1 only.",
            "Return Markdown only. Do not write any prose chapters. Be concrete, internally "
            "consistent, and keep the Arc 1 recurring cast to ten characters or fewer.",
            "MASTER BRIEF:\n" + brief,
        ]),
        system=("You are a rigorous serial-fiction planner. Preserve adult emotional stakes "
                "without explicit sexual content, and do not omit the required cast ledger or "
                "40-chapter outline."),
        temperature=0.45,
    )
    paths.novel_step1.write_text(response.rstrip() + "\n", encoding="utf-8")
    state["step_1"] = {"status": "generated", "approved": False,
                       "generated_at": _now()}
    store.save_json(paths.novel_state, state)
    return {"status": "generated", "path": paths.novel_step1}


def approve_step_1(paths: ProjectPaths) -> None:
    ensure_workspace(paths)
    if not paths.novel_step1.exists():
        raise NovelError("Step 1 has not been generated. Run `anime novel step1` first.")
    state = store.load_json(paths.novel_state)
    state["step_1"] = {"status": "approved", "approved": True, "approved_at": _now()}
    store.save_json(paths.novel_state, state)


def configure_bucket(paths: ProjectPaths, bucket: str) -> str:
    """Record the author-selected Cloud Storage bucket for Vertex batch staging."""
    name = _bucket_name(bucket)
    if not name:
        raise NovelError("Provide a Cloud Storage bucket name, without `gs://`.")
    providers = store.load_json(paths.providers)
    providers.setdefault("novel", {})["gcs_bucket"] = name
    store.save_json(paths.providers, providers)
    return name


def submit_chapter_batch(paths: ProjectPaths, *, start: int | None, count: int,
                         force: bool = False, dry_run: bool = False) -> dict:
    """Submit one resumable Vertex batch window and persist its local manifest."""
    ensure_workspace(paths)
    if count < 1:
        raise NovelError("Chapter count must be at least one.")
    state = store.load_json(paths.novel_state)
    if not state.get("step_1", {}).get("approved"):
        raise NovelError("Step 1 requires your approval. Review novel/planning/step_1.md, "
                         "then run `anime novel approve-step1`.")
    if any(entry.get("status") in {"submitted", "running"}
           for entry in state.get("batches", {}).values()):
        raise NovelError("A chapter batch is already active. Run `anime novel collect` before "
                         "submitting the next continuity window.")

    config = _vertex_config(paths, require_bucket=not dry_run)
    limit = int(config.get("max_batch_chapters", DEFAULT_MAX_BATCH_CHAPTERS))
    if count > limit:
        raise NovelError(
            f"Requested {count} chapters, but this project caps one continuity window at {limit}. "
            "Submit successive windows after collection so the next batch receives the updated canon.")
    chapter_numbers = _pending_chapters(paths, start=start, count=count, force=force)
    if not chapter_numbers:
        return {"status": "skipped", "chapters": []}

    batch_id = _next_batch_id(paths, chapter_numbers)
    requests = _chapter_requests(paths, chapter_numbers, config)
    local_input = paths.novel_batches / f"{batch_id}.input.jsonl"
    local_input.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in requests) + "\n",
                           encoding="utf-8")
    if dry_run:
        return {"status": "planned", "batch_id": batch_id, "chapters": chapter_numbers,
                "input": local_input}

    prefix = str(config.get("gcs_prefix", f"anime-studio/{paths.root.name}/novel")).strip("/")
    input_object = f"{prefix}/inputs/{batch_id}.jsonl"
    output_prefix = f"{prefix}/outputs/{batch_id}"
    storage = _CloudStorage()
    storage.upload(config["gcs_bucket"], input_object, local_input.read_bytes(), "application/jsonl")
    input_uri = _gs_uri(config["gcs_bucket"], input_object)
    output_uri = _gs_uri(config["gcs_bucket"], output_prefix)
    job = _create_batch_job(config, batch_id, input_uri, output_uri)
    manifest = {
        "id": batch_id,
        "status": "submitted",
        "submitted_at": _now(),
        "chapters": chapter_numbers,
        "job_name": job.get("name", ""),
        "input_uri": input_uri,
        "output_uri": output_uri,
        "local_input": str(local_input.relative_to(paths.root)),
        "force": force,
    }
    if not manifest["job_name"]:
        raise NovelError(f"Vertex returned no batch job name: {job}")
    _save_manifest(paths, manifest)
    state.setdefault("batches", {})[batch_id] = manifest
    store.save_json(paths.novel_state, state)
    return {"status": "submitted", "batch_id": batch_id, "chapters": chapter_numbers,
            "job_name": manifest["job_name"]}


def collect_chapter_batch(paths: ProjectPaths, *, force: bool = False) -> dict:
    """Poll and collect one submitted batch into individual Markdown chapter files."""
    ensure_workspace(paths)
    state = store.load_json(paths.novel_state)
    manifests = [entry for entry in state.get("batches", {}).values()
                 if entry.get("status") in {"submitted", "running"}]
    if not manifests:
        return {"status": "skipped", "reason": "no active batch", "written": []}
    manifest = sorted(manifests, key=lambda entry: entry.get("submitted_at", ""))[0]
    config = _vertex_config(paths, require_bucket=True)
    job = _get_batch_job(config, manifest["job_name"])
    job_state = job.get("state", "JOB_STATE_UNSPECIFIED")
    manifest["vertex_state"] = job_state
    if job_state in {"JOB_STATE_PENDING", "JOB_STATE_RUNNING", "JOB_STATE_QUEUED"}:
        manifest["status"] = "running"
        _persist_batch_state(paths, state, manifest)
        return {"status": "running", "batch_id": manifest["id"], "vertex_state": job_state,
                "written": []}

    written, failures = _collect_outputs(paths, config, manifest,
                                         force=force or bool(manifest.get("force")))
    manifest["status"] = "collected" if not failures else "partial"
    manifest["collected_at"] = _now()
    manifest["vertex_state"] = job_state
    manifest["written"] = written
    manifest["failures"] = failures
    _persist_batch_state(paths, state, manifest)
    return {"status": manifest["status"], "batch_id": manifest["id"],
            "vertex_state": job_state, "written": written, "failures": failures}


def _chapter_requests(paths: ProjectPaths, chapter_numbers: Iterable[int], config: dict) -> list[dict]:
    brief = _required_text(paths.novel_brief, "Novel brief")
    step_1 = _required_text(paths.novel_step1, "Approved Step 1")
    canon = paths.novel_canon.read_text(encoding="utf-8").strip() if paths.novel_canon.exists() else (
        "No drafted chapters yet. Establish canon strictly from the approved Step 1 plan.")
    system = (
        "You are the prose author for a continuous adult neo-noir novel. Write mature but "
        "non-explicit fiction. Maintain causal continuity, do not add unplanned major characters, "
        "and follow the exact approved outline for the requested chapter. Finish every scene and "
        "reserve room for the required canon trailer."
    )
    rows = []
    for number in chapter_numbers:
        prompt = "\n\n".join([
            f"NOVEL_CHAPTER_ID: {number:03d}",
            "Write this chapter only. The complete output must be Markdown prose beginning with "
            f"`# Chapter {number}:`, contain no planning commentary, and be 1,600–1,900 words. "
            "End the prose on a complete sentence before the canon trailer.",
            "After the prose, append exactly one hidden HTML comment in this form: "
            "`<!-- NOVEL_CANON {\"summary\":\"...\",\"facts\":[\"...\"],\"open_threads\":[\"...\"]} -->`. "
            "The JSON must be valid, compact, and describe only canon established in this chapter.",
            "MASTER BRIEF:\n" + brief,
            "APPROVED STEP 1 PLAN:\n" + step_1,
            "CANON AT THE START OF THIS BATCH WINDOW:\n" + canon,
        ])
        rows.append({"request": {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": int(config.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)),
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        }})
    return rows


def _collect_outputs(paths: ProjectPaths, config: dict, manifest: dict, *, force: bool) -> tuple[list[int], list[str]]:
    bucket, prefix = _split_gs_uri(manifest["output_uri"])
    objects = _CloudStorage().list(bucket, prefix)
    result_objects = [name for name in objects if name.endswith(".jsonl")]
    if not result_objects:
        return [], ["Vertex finished without a JSONL output object."]
    written: list[int] = []
    failures: list[str] = []
    for object_name in result_objects:
        raw = _CloudStorage().download(bucket, object_name).decode("utf-8")
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                failures.append("Vertex output included invalid JSONL.")
                continue
            chapter = _chapter_from_output(item)
            if chapter is None:
                failures.append("Could not map one Vertex output row to a chapter number.")
                continue
            if item.get("status"):
                failures.append(f"chapter_{chapter:03d}: {item['status']}")
                continue
            text = _response_text(item)
            if not text:
                failures.append(f"chapter_{chapter:03d}: empty model response")
                continue
            chapter_path = paths.novel_chapters / f"chapter_{chapter:03d}.md"
            if chapter_path.exists() and not force:
                continue
            prose, update = _split_canon_trailer(text)
            if not update:
                failures.append(f"chapter_{chapter:03d}: missing required canon trailer; output not saved")
                continue
            chapter_path.write_text(prose.rstrip() + "\n", encoding="utf-8")
            update["chapter"] = chapter
            store.save_json(paths.novel_canon_updates / f"chapter_{chapter:03d}.json", update)
            written.append(chapter)
    _rebuild_canon(paths)
    return sorted(set(written)), failures


def _rebuild_canon(paths: ProjectPaths) -> None:
    entries = []
    for update_path in sorted(paths.novel_canon_updates.glob("chapter_*.json")):
        update = store.load_json(update_path)
        number = int(update.get("chapter", 0))
        entries.append(f"## Chapter {number:03d}\n\n{update.get('summary', '').strip()}")
        for label, key in (("Facts", "facts"), ("Open threads", "open_threads")):
            values = [str(value).strip() for value in update.get(key, []) if str(value).strip()]
            if values:
                entries.append(f"### {label}\n" + "\n".join(f"- {value}" for value in values))
    if entries:
        paths.novel_canon.write_text("# Novel Canon Ledger\n\n" + "\n\n".join(entries) + "\n",
                                     encoding="utf-8")


def _chapter_from_output(item: dict) -> int | None:
    parts = item.get("request", {}).get("contents", [{}])[0].get("parts", [])
    prompt = "".join(str(part.get("text", "")) for part in parts)
    match = _CHAPTER_ID.search(prompt)
    return int(match.group(1)) if match else None


def _response_text(item: dict) -> str:
    candidates = item.get("response", {}).get("candidates") or []
    if not candidates:
        return ""
    return "".join(part.get("text", "") for part in
                   candidates[0].get("content", {}).get("parts", []))


def _split_canon_trailer(text: str) -> tuple[str, dict]:
    match = _CANON_TRAILER.search(text.strip())
    if not match:
        return text, {}
    try:
        update = json.loads(match.group(1))
    except json.JSONDecodeError:
        return text, {}
    return text[:match.start()].rstrip(), update if isinstance(update, dict) else {}


def _pending_chapters(paths: ProjectPaths, *, start: int | None, count: int, force: bool) -> list[int]:
    first = start or 1
    numbers = []
    candidate = first
    while len(numbers) < count:
        path = paths.novel_chapters / f"chapter_{candidate:03d}.md"
        if force or not path.exists():
            numbers.append(candidate)
        candidate += 1
    return numbers


def _next_batch_id(paths: ProjectPaths, chapters: list[int]) -> str:
    serial = len(list(paths.novel_batches.glob("*.manifest.json"))) + 1
    return f"batch_{serial:03d}_{chapters[0]:03d}_{chapters[-1]:03d}"


def _save_manifest(paths: ProjectPaths, manifest: dict) -> None:
    store.save_json(paths.novel_batches / f"{manifest['id']}.manifest.json", manifest)


def _persist_batch_state(paths: ProjectPaths, state: dict, manifest: dict) -> None:
    state.setdefault("batches", {})[manifest["id"]] = manifest
    _save_manifest(paths, manifest)
    store.save_json(paths.novel_state, state)


def _vertex_config(paths: ProjectPaths, *, require_bucket: bool) -> dict:
    config = store.load_json(paths.providers).get("novel", {})
    project = str(config.get("project", "")).strip()
    if not project:
        raise NovelError("providers.json needs novel.project for Vertex novel generation.")
    result = {
        "project": project,
        "location": str(config.get("location", "global")).strip() or "global",
        "model": str(config.get("model", "gemini-3.5-flash")).strip() or "gemini-3.5-flash",
        "gcs_bucket": _bucket_name(str(config.get("gcs_bucket", ""))),
        "gcs_prefix": str(config.get("gcs_prefix", "")).strip("/"),
        "max_batch_chapters": int(config.get("max_batch_chapters", DEFAULT_MAX_BATCH_CHAPTERS)),
        "max_output_tokens": int(config.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)),
    }
    if require_bucket and not result["gcs_bucket"]:
        raise NovelError("providers.json needs novel.gcs_bucket before Vertex Batch can run. "
                         "Use an existing Cloud Storage bucket in the Vertex batch region.")
    return result


def _create_batch_job(config: dict, batch_id: str, input_uri: str, output_uri: str) -> dict:
    body = {
        "displayName": f"novel-{batch_id}",
        "model": f"publishers/google/models/{config['model']}",
        "inputConfig": {"instancesFormat": "jsonl", "gcsSource": {"uris": [input_uri]}},
        "outputConfig": {"predictionsFormat": "jsonl",
                         "gcsDestination": {"outputUriPrefix": output_uri}},
    }
    return _vertex_request(config, "POST", "batchPredictionJobs", body)


def _get_batch_job(config: dict, name: str) -> dict:
    return _vertex_request(config, "GET", name)


def _vertex_url(config: dict, suffix: str) -> str:
    location = config["location"]
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    suffix = urllib.parse.quote(suffix, safe="/")
    if suffix.startswith("projects/"):
        # Batch API responses return a fully-qualified resource name.  GET requests
        # must use it directly rather than nesting it below the configured parent.
        return f"https://{host}/v1/{suffix}"
    return f"https://{host}/v1/projects/{config['project']}/locations/{location}/{suffix}"


def _vertex_request(config: dict, method: str, suffix: str, body: dict | None = None) -> dict:
    url = _vertex_url(config, suffix)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {gcloud_auth.access_token()}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        try:
            message = json.loads(detail).get("error", {}).get("message", detail)
        except Exception:
            message = detail
        raise NovelError(f"Vertex Batch API {error.code}: {message}") from None
    except urllib.error.URLError as error:
        raise NovelError(f"Could not reach Vertex Batch: {error.reason}") from None


class _CloudStorage:
    """Small OAuth-authenticated Cloud Storage client; no SDK or local CLI needed."""

    def upload(self, bucket: str, object_name: str, data: bytes, content_type: str) -> None:
        query = urllib.parse.urlencode({"uploadType": "media", "name": object_name})
        self._request("POST", f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?{query}",
                      data=data, content_type=content_type)

    def download(self, bucket: str, object_name: str) -> bytes:
        name = urllib.parse.quote(object_name, safe="")
        return self._request("GET", f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{name}?alt=media",
                             raw=True)

    def list(self, bucket: str, prefix: str) -> list[str]:
        result: list[str] = []
        token = ""
        while True:
            query = {"prefix": prefix}
            if token:
                query["pageToken"] = token
            payload = self._request("GET", "https://storage.googleapis.com/storage/v1/b/"
                                    f"{bucket}/o?{urllib.parse.urlencode(query)}")
            result.extend(str(item.get("name", "")) for item in payload.get("items", []))
            token = str(payload.get("nextPageToken", ""))
            if not token:
                return result

    @staticmethod
    def _request(method: str, url: str, *, data: bytes | None = None,
                 content_type: str = "application/json", raw: bool = False):
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {gcloud_auth.access_token()}")
        if data is not None:
            request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise NovelError(f"Cloud Storage API {error.code}: {detail[:300]}") from None
        except urllib.error.URLError as error:
            raise NovelError(f"Could not reach Cloud Storage: {error.reason}") from None
        return payload if raw else json.loads(payload.decode("utf-8"))


def _required_text(path: Path, label: str) -> str:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        raise NovelError(f"{label} is missing at {path}.")
    return path.read_text(encoding="utf-8").strip()


def _bucket_name(value: str) -> str:
    value = value.strip().removeprefix("gs://").strip("/")
    if "/" in value:
        raise NovelError("novel.gcs_bucket must be a bucket name, not a gs:// path.")
    return value


def _gs_uri(bucket: str, object_name: str) -> str:
    return f"gs://{bucket}/{object_name.strip('/')}"


def _split_gs_uri(uri: str) -> tuple[str, str]:
    stripped = uri.removeprefix("gs://")
    bucket, separator, prefix = stripped.partition("/")
    if not bucket or not separator:
        raise NovelError(f"Invalid Cloud Storage URI: {uri}")
    return bucket, prefix


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
