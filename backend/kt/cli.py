"""``kt`` command line: init, sources, sync, build, demo, serve, mcp, worker, search."""

from __future__ import annotations

import argparse
import json
import logging
import secrets
import sys
from pathlib import Path

from kt.config import get_settings

DEV_KEYS = {
    "dev-admin-key": {"principal": "user:admin", "groups": ["group:engineering", "group:hr"], "roles": ["admin"]},
    "dev-engineering-key": {"principal": "user:eva", "groups": ["group:engineering"], "roles": []},
    "dev-hr-key": {"principal": "user:harry", "groups": ["group:hr"], "roles": []},
    "dev-agent-key": {"principal": "agent:assistant", "groups": ["group:engineering"], "roles": []},
}


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def cmd_init(args) -> None:
    from kt.db.session import init_db

    init_db()
    settings = get_settings()
    keys_path = settings.api_keys_file or settings.data_dir / "api-keys.json"
    if not keys_path.exists():
        keys = DEV_KEYS if args.dev_keys else {
            "kt_" + secrets.token_urlsafe(24): {"principal": "user:admin", "groups": [], "roles": ["admin"]}}
        keys_path.write_text(json.dumps(keys, indent=2), encoding="utf-8")
        print(f"API keys written to {keys_path}")
    print(f"Database ready: {settings.database_url}")


def _register(connector_type: str, name: str, config: dict) -> str:
    from kt.connectors import get_connector
    from kt.db.session import init_db, session_scope
    from kt.ingestion.service import IngestionService
    from kt.semantic.embeddings import get_embedder
    from kt.storage.vector import get_vector_store

    init_db()
    get_connector(connector_type, config).validate()
    with session_scope() as s:
        src = IngestionService(s, get_embedder(), get_vector_store()).register_source(
            get_settings().default_tenant, connector_type, name, config)
        return src.id


def cmd_source_add(args) -> None:
    if args.type == "filesystem":
        config = {"path": str(Path(args.path).resolve())}
        if args.groups:
            config["default_principals"] = args.groups.split(",")
    else:
        config = {"base_url": args.base_url, "email": args.email, "api_token_env": args.token_env,
                  "spaces": args.spaces.split(","), "reconcile_hours": 24}
        if args.space_principals:
            config["space_principals"] = json.loads(args.space_principals)
    print(_register(args.type, args.name, config))


def cmd_source_list(args) -> None:
    from kt.db.orm import Source
    from kt.db.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        _print([{"id": x.id, "name": x.name, "type": x.connector_type, "status": x.status,
                 "last_synced_at": x.last_synced_at} for x in s.query(Source).all()])


def cmd_sync(args) -> None:
    from kt import jobs
    from kt.db.session import init_db

    init_db()
    result = {args.source: jobs.sync_source(args.source, full=args.full).as_dict()} if args.source \
        else jobs.sync_all(full=args.full)
    _print(result)
    if not args.no_build and jobs.topology_dirty():
        _print(jobs.rebuild_topology())


def cmd_build(args) -> None:
    from kt import jobs
    from kt.db.session import init_db

    init_db()
    _print(jobs.rebuild_topology())


def cmd_demo(args) -> None:
    """Ingest the bundled demo corpus, build a snapshot, then apply an update and build a second one."""
    import os

    from kt import jobs

    candidates = [Path(os.environ["KT_DEMO_DIR"])] if os.environ.get("KT_DEMO_DIR") else []
    candidates += [Path(__file__).resolve().parents[2] / "demo", Path.cwd().parent / "demo", Path.cwd() / "demo",
                   Path("/app/demo")]
    demo_dir = next((c for c in candidates if (c / "corpus").is_dir()), None)
    if demo_dir is None and not args.corpus:
        sys.exit("Demo corpus not found; pass --corpus or set KT_DEMO_DIR")
    corpus = Path(args.corpus) if args.corpus else demo_dir / "corpus"
    update = Path(args.update) if args.update else (demo_dir / "corpus-update" if demo_dir else Path("-"))
    args.dev_keys = True
    cmd_init(args)
    sid = _register("filesystem", "Demo wiki", {"path": str(corpus.resolve()), "base_url": "https://wiki.example.com"})
    _print(jobs.sync_source(sid).as_dict())
    first = jobs.rebuild_topology()
    _print(first)
    if update.is_dir() and not args.no_update:
        sid2 = _register("filesystem", "Demo wiki — new payments platform",
                         {"path": str(update.resolve()), "base_url": "https://wiki.example.com/v2"})
        _print(jobs.sync_source(sid2).as_dict())
        _print(jobs.rebuild_topology())
    print("\nDemo ready. Start the API:  kt serve   then open http://127.0.0.1:8000  (key: dev-admin-key)")


def cmd_serve(args) -> None:
    import uvicorn

    uvicorn.run("kt.api.main:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)


def cmd_mcp(args) -> None:
    from kt.mcp.server import main

    main("http" if args.http else "stdio")


def cmd_worker(args) -> None:
    from kt.db.session import init_db
    from kt.jobs import worker_loop

    init_db()
    worker_loop(args.interval)


def cmd_search(args) -> None:
    from kt.db.session import init_db, session_scope
    from kt.runtime import principal_from_api_key
    from kt.semantic.embeddings import get_embedder
    from kt.services import KnowledgeService
    from kt.storage.vector import get_vector_store

    init_db()
    with session_scope() as s:
        svc = KnowledgeService(s, principal_from_api_key(args.key), get_embedder(), get_vector_store())
        _print(svc.search(args.query, top_k=args.top_k, domain_id=args.domain))


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stderr)
    p = argparse.ArgumentParser(prog="kt", description="Knowledge Topology")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="create tables and API keys")
    sp.add_argument("--dev-keys", action="store_true", help="write well-known development keys (local only!)")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("source", help="manage sources")
    ssub = sp.add_subparsers(dest="source_cmd", required=True)
    add = ssub.add_parser("add")
    add.add_argument("type", choices=["filesystem", "confluence"])
    add.add_argument("--name", required=True)
    add.add_argument("--path")
    add.add_argument("--groups", help="filesystem: default read principals, e.g. group:engineering")
    add.add_argument("--base-url")
    add.add_argument("--email")
    add.add_argument("--token-env", default="CONFLUENCE_API_TOKEN")
    add.add_argument("--spaces", default="")
    add.add_argument("--space-principals", help='JSON, e.g. {"ENG": ["group:engineering"]}')
    add.set_defaults(func=cmd_source_add)
    ls = ssub.add_parser("list")
    ls.set_defaults(func=cmd_source_list)

    sp = sub.add_parser("sync", help="sync sources (incremental by default) and rebuild topology if needed")
    sp.add_argument("--source")
    sp.add_argument("--full", action="store_true")
    sp.add_argument("--no-build", action="store_true")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("build", help="build a new topology snapshot")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("demo", help="load the demo corpus (two snapshots)")
    sp.add_argument("--corpus")
    sp.add_argument("--update")
    sp.add_argument("--no-update", action="store_true")
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("serve", help="run the REST API (+ web UI if built)")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--reload", action="store_true")
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("mcp", help="run the MCP server (stdio; --http for Streamable HTTP)")
    sp.add_argument("--http", action="store_true")
    sp.set_defaults(func=cmd_mcp)

    sp = sub.add_parser("worker", help="periodic sync + rebuild loop")
    sp.add_argument("--interval", type=int, default=900)
    sp.set_defaults(func=cmd_worker)

    sp = sub.add_parser("search", help="search as a given API key")
    sp.add_argument("query")
    sp.add_argument("--key", default="dev-admin-key")
    sp.add_argument("--top-k", type=int, default=5)
    sp.add_argument("--domain")
    sp.set_defaults(func=cmd_search)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
