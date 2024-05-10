import logging
import pathlib
import sys
import json
from copy import deepcopy

import click

from .constant import PREFIX_TARGET
from .context import CommonContext
from .context import registry as context_registry
from .document import Omnifest
from .help.log import JSONSequenceHandler
from .target import registry as target_registry
from .transform import resolve

log = logging.getLogger(__name__)


@click.group()
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Sets verbosity. Can be passed multiple times to be more verbose.",
)
@click.option(
    "-j/",
    "--json/--no-json",
    default=False,
    help="Sets output format to JSONseq. Output on stderr will be JSONseq records with ASCII record separators.",
)
@click.option(
    "-i",
    "--identifier",
    help="An identifier to include in all log records generated by `otk -j`. Can only be used together with `-j`.",
)
@click.option(
    "-w",
    "--warn",
    type=click.Choice(["duplicate-definition"]),
    multiple=True,
    help="Enable warnings, can be passed multiple times.",
)
@click.pass_context
def root(
    ctx: click.Context, verbose: int, json: bool, identifier: str, warn: list[str]
) -> None:
    """`otk` is the omnifest toolkit. A program to work with omnifest inputs
    and translate them into the native formats for image build tooling."""

    ctx.ensure_object(dict)

    logging.basicConfig(
        level=logging.WARNING - (10 * verbose),
        handlers=[
            (
                JSONSequenceHandler(identifier, stream=sys.stderr)
                if json
                else logging.StreamHandler()
            )
        ],
    )

    # This context is passed along to all other subcommands.
    ctx.obj["context"] = {
        "duplicate_definitions_warning": "duplicate-definition" in warn,
    }

    # We do this check *after* setting up the handlers so the error is formatted
    if identifier and not json:
        log.error("cannot use `-i` without also using `-j`")
        sys.exit(1)


@root.command()
@click.argument("input", type=click.Path(exists=True))
@click.argument("output", type=click.Path(), required=False)
@click.option(
    "--external/--no-external",
    default=True,
    help="Process external directives.",
)
@click.option("-t", "--target", "requested_target", required=False)
@click.pass_context
def compile(
    ctx: click.Context,
    input: str,
    output: str | None,
    external: bool,
    requested_target: str,
) -> None:
    """Compile a given omnifest into its targets."""

    log.info("Compiling the input file %r to %r", input, output or "STDOUT")

    file = pathlib.Path(input)
    root = file.parent

    # TODO posixpath serializer for json output
    log.info("include root is %r", str(root))

    ctx = CommonContext(root, **ctx.obj["context"])
    doc = Omnifest.from_yaml_path(file)

    tree = resolve(ctx, doc.tree)

    if not external:
        print(json.dumps(tree, indent=2))
        return 1

    # TODO We would probably want to generalize extraction of these sections.
    # TODO And we probably want to do it earlier so we can bail out if multiple
    # TODO targets are in the omnifest but none is selected.

    # Now that the tree has been generally resolved we're going to resolve the
    # specific targets to export. We select them based on prefix.
    available_targets = {
        key.removeprefix(PREFIX_TARGET): deepcopy(value)
        for key, value in tree.items()
        if key.startswith(PREFIX_TARGET)
    }

    if len(available_targets) == 0:
        log.fatal("omnifest does not contain any targets")
        return 1

    if not requested_target:
        if len(available_targets) > 1:
            log.fatal(
                "omnifest contains multiple targets, please select one with `-t`: %r",
                list(available_targets.keys()),
            )
            return 1
        else:
            requested_target = list(available_targets.keys())[0]

    if requested_target not in available_targets:
        log.fatal(
            "omnifest does not contain target %r, available: %r"
            % (
                requested_target,
                list(available_targets.keys()),
            )
        )
        return 1

    name = requested_target
    tree = available_targets[name]

    kind = name.split(".")[0]

    context = context_registry[kind](ctx)
    target = target_registry[kind]()

    # This time we resolve with a kind
    tree = resolve(context, tree)

    # And output with a target
    print(target.as_string(context, tree))
