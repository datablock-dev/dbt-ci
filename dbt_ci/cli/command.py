"""Click command and group classes shared by every dbt-ci command."""

import click


def drop_empty_option_values(params: list[click.Parameter], args: list[str]) -> list[str]:
    """
    Remove options given an empty value, so they count as not passed at all.

    CI templates often pass a flag whether or not its input is set, e.g.
    `--vars '${{ inputs.vars }}'`, which becomes `--vars ''` when the input is empty. Taken
    literally, that empty value would beat the config file, the selected profile, the
    environment and what init recorded. Dropping it lets those apply instead. Both
    `--opt ''` and `--opt=` forms are handled; arguments after `--` are left untouched.
    """
    value_options = {
        name
        for param in params
        if isinstance(param, click.Option) and not param.is_flag and param.nargs == 1
        for name in param.opts
    }

    kept: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            kept.extend(args[index:])
            break
        if token in value_options and index + 1 < len(args) and not args[index + 1].strip():
            index += 2
            continue
        name, separator, value = token.partition("=")
        if separator and name.startswith("--") and name in value_options and not value.strip():
            index += 1
            continue
        kept.append(token)
        index += 1
    return kept


class DbtCiCommand(click.Command):
    """A command whose options treat an empty value as not passed."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Drop options given an empty value before Click parses the arguments."""
        return super().parse_args(ctx, drop_empty_option_values(self.get_params(ctx), args))


class DbtCiGroup(click.Group):
    """A group whose own options, commands and subgroups treat empty values as not passed."""

    command_class = DbtCiCommand
    # Subgroups (e.g. `ephemeral`) are created with this same class
    group_class = type

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Drop the group's own options given an empty value before Click parses them."""
        return super().parse_args(ctx, drop_empty_option_values(self.get_params(ctx), args))
