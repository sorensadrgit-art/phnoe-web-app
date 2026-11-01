"""Click one-shot commands and read-only, memory-history REPL."""
import json
import os
import shlex
import subprocess
import sys
from functools import wraps
from pathlib import Path

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory

from cli_anything.kinelab.core.operator import BOUNDED_CHECKS, identity, inspect_package, quality, verify_evidence
from cli_anything.kinelab.utils.kinelab_backend import refuse_live_path
from cli_anything.kinelab.utils.repl_skin import ReplSkin


def handle_error(function):
    """Emit actionable, machine-readable backend failures without substitution."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            click.echo(json.dumps({"status": "BLOCKED", "error": str(error)}))
            raise click.exceptions.Exit(2) from error
    return wrapped


def _emit(ctx: click.Context, report: dict, code: int = 0) -> None:
    click.echo(json.dumps(report, indent=None if ctx.obj["json"] else 2, allow_nan=False))
    if code:
        ctx.exit(code)


@click.group(invoke_without_command=True)
@click.option("--workspace", type=click.Path(path_type=Path, file_okay=False), required=True,
              help="Explicit trusted KineLab source checkout; never searches app data.")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable JSON reports.")
@click.pass_context
def cli(ctx: click.Context, workspace: Path, json_output: bool) -> None:
    """Read-only KineLab engineering verification; no clinical acceptance claim.

    No recording, capture, mutation, export or deployment command exists.
    """
    ctx.obj = {"workspace": workspace, "json": json_output}
    if "--help" not in sys.argv[1:] and "-h" not in sys.argv[1:]:
        try:
            refuse_live_path(workspace)
        except ValueError as error:
            click.echo(json.dumps({"status": "BLOCKED", "error": str(error)}))
            raise click.exceptions.Exit(2) from error
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


@cli.group()
def quality_group() -> None:
    """Plan or execute bounded existing quality probes."""


@quality_group.command("plan")
@click.option("--check", "checks", multiple=True, type=click.Choice(BOUNDED_CHECKS), default=("python-runtime",))
@click.pass_context
@handle_error
def quality_plan(ctx: click.Context, checks: tuple[str, ...]) -> None:
    """Print the actual NOT_RUN backend plan; no checks execute."""
    report = quality(ctx.obj["workspace"], list(checks), execute=False)
    _emit(ctx, report, 3)


@quality_group.command("run")
@click.option("--check", "checks", multiple=True, required=True, type=click.Choice(BOUNDED_CHECKS))
@click.pass_context
@handle_error
def quality_run(ctx: click.Context, checks: tuple[str, ...]) -> None:
    """Run only the explicitly chosen runtime/syntax probes, bounded to 60s each."""
    report = quality(ctx.obj["workspace"], list(checks), execute=True)
    _emit(ctx, report, {"PASS": 0, "FAIL": 1, "BLOCKED": 2, "NOT_RUN": 3}[report["status"]])


# Keep the public command named quality while retaining a Python import alias.
cli.add_command(quality_group, "quality")
cli.commands.pop("quality-group", None)


@cli.group()
def evidence() -> None:
    """Use the independent offline evidence verifier."""


@evidence.command("verify")
@click.argument("archive", type=click.Path(path_type=Path, dir_okay=False))
@click.pass_context
@handle_error
def evidence_verify(ctx: click.Context, archive: Path) -> None:
    """Verify one explicit archive without restoring or modifying it."""
    result, code = verify_evidence(ctx.obj["workspace"], archive)
    _emit(ctx, result, code)


@cli.group()
def package() -> None:
    """Inspect distribution metadata without building or rewriting packages."""


@package.command("inspect")
@click.argument("manifest", type=click.Path(path_type=Path, dir_okay=False))
@click.pass_context
@handle_error
def package_inspect(ctx: click.Context, manifest: Path) -> None:
    """Report manifest hash and stored claims; payload verification is NOT_RUN."""
    _emit(ctx, inspect_package(ctx.obj["workspace"], manifest))


@cli.command("identity")
@click.pass_context
@handle_error
def identity_command(ctx: click.Context) -> None:
    """Report workspace path, git HEAD and current source SHA-256 identities."""
    _emit(ctx, identity(ctx.obj["workspace"]))


@cli.command()
@click.pass_context
def repl(ctx: click.Context) -> None:
    """Enter a read-only REPL with in-memory history; exit/quit ends it."""
    skin = ReplSkin("kinelab", version="0.1.0", history_file=os.devnull,
                    skill_path=str(Path(__file__).parent / "skills/SKILL.md"))
    if not ctx.obj["json"]:
        skin.print_banner()
    session: PromptSession[str] | None = PromptSession(history=InMemoryHistory()) if sys.stdin.isatty() else None
    while True:
        try:
            line = skin.get_input(session) if session else sys.stdin.readline()
            if not line or line.strip() in {"exit", "quit"}:
                break
            if line.strip() == "help":
                click.echo(cli.get_help(ctx))
                continue
            args = shlex.split(line, posix=False)
            if not args or args[0] == "repl":
                continue
            # Strip matching shell quotes after Windows-safe tokenization.
            args = [a[1:-1] if len(a)>1 and a[0]==a[-1] and a[0] in "\"'" else a for a in args]
            cli.main(["--workspace", str(ctx.obj["workspace"]), *( ["--json"] if ctx.obj["json"] else []), *args], standalone_mode=False)
        except (EOFError, KeyboardInterrupt):
            break
        except (click.ClickException, ValueError) as error:
            click.echo(json.dumps({"status": "BLOCKED", "error": str(error)}))
    if not ctx.obj["json"]:
        skin.print_goodbye()


def main() -> None:
    """Installed console entry point."""
    sys.dont_write_bytecode = True
    try:
        code = cli.main(standalone_mode=False)
    except click.ClickException as error:
        if "--json" in sys.argv:
            click.echo(json.dumps({"status": "BLOCKED", "error": error.format_message()}))
        else:
            error.show()
        raise SystemExit(error.exit_code) from error
    if isinstance(code, int):
        raise SystemExit(code)


if __name__ == "__main__":
    main()
