# -*- coding: utf-8 -*-
"""
.. module: gitlab_groupsync.cli
   :synopsis: CLI interface
.. moduleauthor:: "Josef Nevrly <josef.nevrly@gmail.com>"
"""

import sys
import pkg_resources
import click
from onacol import ConfigManager, ConfigValidationError


DEFAULT_CONFIG_FILE = pkg_resources.resource_filename(
    "gitlab_groupsync", "default_config.yaml")



@click.command(context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.option("--config", type=click.Path(exists=True), default=None,
              help="Path to the configuration file.")
@click.option("--get-config-template", type=click.File("w"), default=None,
              help="Write default configuration template to the file.")
@click.pass_context
def main(ctx, config, get_config_template):
    """Console script for gitlab_groupsync."""
    # Instantiate config_manager
    config_manager = ConfigManager(
        DEFAULT_CONFIG_FILE,
        env_var_prefix="gitlab_groupsync",
        optional_files=[config] if config else []
    )

    # Generate configuration for the --get-config-template option
    # Then finish the application
    if get_config_template:
        config_manager.generate_config_example(get_config_template)
        sys.exit(0)

    # Load (implicit) environment variables
    config_manager.config_from_env_vars()

    # Parse all extra command line options
    config_manager.config_from_cli_args(ctx.args)

    # Validate the config
    try:
        config_manager.validate()
    except ConfigValidationError as cve:
        click.secho("<----------------Configuration problem---------------->",
                    fg='red')
        # Logging is not yet configured at this point.
        click.secho(str(cve), fg='red', err=True)
        sys.exit(1)

    click.echo("Replace this message by putting your code into "
               "gitlab_groupsync.cli.main")
    click.echo("See click documentation at https://click.palletsprojects.com/")
    sys.exit(0)


if __name__ == "__main__":
    main()  # pragma: no cover
