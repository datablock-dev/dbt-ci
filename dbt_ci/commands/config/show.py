"""Implementation of `dbt-ci config show`: the settings a command would run with."""

import json
import os
from argparse import Namespace
from dataclasses import asdict, dataclass
from typing import Any

import click
from click.core import ParameterSource

from dbt_ci.cli.command import DbtCiCommand
from dbt_ci.cli.common_options import common_options
from dbt_ci.cli.config.parser import TOP_LEVEL, config_provenance
from dbt_ci.dbt.flags import INHERITED_FROM_INIT, get_cached_value
from dbt_ci.utilities.logging import redact

DEFAULT_COMMAND = "init"
INHERITED = "inherited from init"
# Sources hidden unless --all is passed: nothing chose these values
QUIET_SOURCES = {"default", "not set"}


def _common_option_names() -> set[str]:
    """Return the parameter names every command shares, from the common_options decorator."""
    probe = common_options(click.Command("probe"))
    return {param.name for param in probe.params if param.name}


@dataclass
class Setting:
    """One option of a command, with the value it resolves to and where that came from."""

    option: str
    value: Any
    source: str
    # True for the options every command shares, False for the command's own
    common: bool = False


@dataclass
class ResolvedSettings:
    """Every option a command would run with, plus the config file and profile in use."""

    command: str
    config_file: str | None
    profile: str | None
    profile_source: str | None
    settings: list[Setting]
    # The event whose `on:` block applied (None for none), and how it was decided; both
    # None when the config file has no `on:` block and --event was not given
    event: str | None = None
    event_reason: str | None = None


def resolve_settings(cli: click.Group, tokens: list[str]) -> ResolvedSettings:
    """
    Resolve a command's options exactly as running it would, without running it.

    tokens is a command line minus `dbt-ci`, e.g. ["run", "--profile", "action"]. The
    leading words select the command (and subcommand); the rest is parsed by that
    command, so flags, the config file, the profile, the environment and the defaults
    combine just as they would in a real run. Without a command, init is used.
    """
    command: click.Command = cli
    path: list[str] = []
    rest = list(tokens)
    while isinstance(command, click.Group) and rest and rest[0] in command.commands:
        path.append(rest[0])
        command = command.commands[rest.pop(0)]
    if rest and not rest[0].startswith("-") and isinstance(command, click.Group):
        known = ", ".join(sorted(name for name in command.commands if name != "config"))
        raise click.UsageError(f"Unknown command '{rest[0]}'. Commands: {known}.")
    if not path:
        path = [DEFAULT_COMMAND]
        command = cli.commands[DEFAULT_COMMAND]
    if isinstance(command, click.Group):
        # A group such as `ephemeral` runs its default action without a subcommand
        command = DbtCiCommand(command.name, params=command.params)

    ctx = command.make_context(f"dbt-ci {' '.join(path)}", rest)
    provenance = config_provenance(ctx)
    settings = [
        _setting(ctx, param, provenance)
        for param in command.get_params(ctx)
        if isinstance(param, click.Option) and not param.hidden and param.name != "help"
    ]
    if path[0] != "init":
        _apply_inherited_values(ctx, settings)
    common = _common_option_names()
    params = {_flag_name(p): p.name for p in command.get_params(ctx) if isinstance(p, click.Option)}
    for setting in settings:
        setting.common = params.get(setting.option) in common
    # The command's own options first, then the shared ones, each alphabetically
    settings.sort(key=lambda setting: (setting.common, setting.option))

    profile_source = None
    if provenance["profile"]:
        profile_param = next(p for p in command.get_params(ctx) if p.name == "profile")
        if provenance["profile_inherited"]:
            profile_source = INHERITED
        else:
            profile_source = _click_source(ctx, profile_param, provenance)

    return ResolvedSettings(
        command=" ".join(path),
        config_file=provenance["path"],
        profile=provenance["profile"],
        profile_source=profile_source,
        settings=settings,
        event=(provenance["event"] or (None, None))[0],
        event_reason=(provenance["event"] or (None, None))[1],
    )


def _setting(ctx: click.Context, param: click.Option, provenance: dict[str, Any]) -> Setting:
    """Build the Setting for one option."""
    name = param.name or ""
    value = ctx.params.get(name)
    if name == "profile" and provenance["profile_inherited"]:
        source = INHERITED
    elif name in provenance["sources"]:
        source = provenance["sources"][name]
    else:
        source = _click_source(ctx, param, provenance)
    return Setting(option=_flag_name(param), value=redact(value, name), source=source)


def _click_source(ctx: click.Context, param: click.Parameter, provenance: dict[str, Any]) -> str:
    """Describe where Click took an option's value from."""
    source = ctx.get_parameter_source(param.name or "")
    if source == ParameterSource.COMMANDLINE:
        return "command line"
    if source == ParameterSource.ENVIRONMENT:
        envvar = _set_envvar(param)
        if envvar in provenance["injected"]:
            # The config file put it in the environment for an option read from there
            return str(provenance["origin"].get(envvar, TOP_LEVEL))
        return f"environment ({envvar})" if envvar else "environment"
    value = ctx.params.get(param.name or "")
    return "default" if value not in (None, (), "") else "not set"


def _set_envvar(param: click.Parameter) -> str | None:
    """Return the first of an option's environment variables that is set and not empty."""
    envvar = param.envvar
    envvars: list[str] = [envvar] if isinstance(envvar, str) else list(envvar or [])
    return next((name for name in envvars if name and os.environ.get(name)), None)


def _apply_inherited_values(ctx: click.Context, settings: list[Setting]) -> None:
    """Fill the settings later commands take from init's cache when they are unset."""
    namespace = Namespace(**ctx.params)
    by_option = {setting.option: setting for setting in settings}
    for param in ctx.command.get_params(ctx):
        if param.name not in INHERITED_FROM_INIT or ctx.params.get(param.name):
            continue
        cached = get_cached_value(namespace, param.name)
        setting = by_option.get(_flag_name(param)) if isinstance(param, click.Option) else None
        if cached and setting is not None:
            setting.value = redact(cached, param.name)
            setting.source = INHERITED


def _flag_name(param: click.Option) -> str:
    """Return the option's long name, e.g. --target."""
    long_names = [name for name in param.opts if name.startswith("--")]
    return long_names[0] if long_names else param.opts[0]


def format_value(value: Any) -> str:
    """Render a value for the table."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) if value else "-"
    return str(value)


def visible(resolved: ResolvedSettings, show_all: bool) -> list[Setting]:
    """Return the settings to display: those something chose, or every one with --all."""
    return [s for s in resolved.settings if show_all or s.source not in QUIET_SOURCES]


def render_table(resolved: ResolvedSettings, show_all: bool) -> str:
    """Render the settings as aligned text tables: the command's own options, then common."""
    settings = visible(resolved, show_all)
    profile = resolved.profile or "none"
    if resolved.profile_source:
        profile += f" ({resolved.profile_source})"
    lines = [
        f"Command:     dbt-ci {resolved.command}",
        f"Config file: {resolved.config_file or 'none found'}",
        f"Profile:     {profile}",
    ]
    if resolved.event_reason:
        lines.append(f"Event:       {resolved.event or 'none'} ({resolved.event_reason})")
    if not settings:
        hint = "" if show_all else " (pass --all to list defaults too)"
        return "\n".join(lines + ["", f"No options are set{hint}."])

    header = ("OPTION", "VALUE", "SOURCE")
    rows = [(s.option, format_value(s.value), s.source) for s in settings]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(2)]

    def line(row: tuple[str, str, str]) -> str:
        """Format one aligned row."""
        return f"{row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  {row[2]}".rstrip()

    for title, common in ((f"{resolved.command} options", False), ("Common options", True)):
        section = [row for row, s in zip(rows, settings) if s.common == common]
        if section:
            lines += ["", title, line(header), *map(line, section)]
    if not show_all:
        lines += ["", "Defaults are hidden; pass --all to list every option."]
    return "\n".join(lines)


def render_json(resolved: ResolvedSettings, show_all: bool) -> str:
    """Render the settings as JSON, hiding defaults and unset options unless asked."""
    data = asdict(resolved)
    data["settings"] = [asdict(s) for s in visible(resolved, show_all)]
    return json.dumps(data, indent=2, default=str)
