import logging
import os

from borgmatic.execute import execute_command, execute_command_with_processes
from borgmatic.hooks import dump

logger = logging.getLogger(__name__)


def make_dump_path(config):  # pragma: no cover
    '''
    Make the dump path from the given configuration dict and the name of this hook.
    '''
    return dump.make_database_dump_path(
        config.get('borgmatic_source_directory'), 'sqlite_databases'
    )


def dump_databases(databases, config, log_prefix, dry_run):
    '''
    Dump the given SQLite3 databases to a file. The databases are supplied as a sequence of
    configuration dicts, as per the configuration schema. Use the given configuration dict to
    construct the destination path and the given log prefix in any log entries. If this is a dry
    run, then don't actually dump anything.
    '''
    dry_run_label = ' (dry run; not actually dumping anything)' if dry_run else ''
    processes = []

    logger.info(f'{log_prefix}: Dumping SQLite databases{dry_run_label}')

    for database in databases:
        database_path = database['path']

        if database['name'] == 'all':
            logger.warning('The "all" database name has no meaning for SQLite3 databases')
        if not os.path.exists(database_path):
            logger.warning(
                f'{log_prefix}: No SQLite database at {database_path}; An empty database will be created and dumped'
            )

        dump_path = make_dump_path(config)
        dump_filename = dump.make_database_dump_filename(dump_path, database['name'])
        if os.path.exists(dump_filename):
            logger.warning(
                f'{log_prefix}: Skipping duplicate dump of SQLite database at {database_path} to {dump_filename}'
            )
            continue

        command = (
            'sqlite3',
            database_path,
            '.dump',
            '>',
            dump_filename,
        )
        logger.debug(
            f'{log_prefix}: Dumping SQLite database at {database_path} to {dump_filename}{dry_run_label}'
        )
        if dry_run:
            continue

        dump.create_parent_directory_for_dump(dump_filename)
        processes.append(execute_command(command, shell=True, run_to_completion=False))

    return processes


def remove_database_dumps(databases, config, log_prefix, dry_run):  # pragma: no cover
    '''
    Remove the given SQLite3 database dumps from the filesystem. The databases are supplied as a
    sequence of configuration dicts, as per the configuration schema. Use the given configuration
    dict to construct the destination path and the given log prefix in any log entries. If this is a
    dry run, then don't actually remove anything.
    '''
    dump.remove_database_dumps(make_dump_path(config), 'SQLite', log_prefix, dry_run)


def make_database_dump_pattern(databases, config, log_prefix, name=None):  # pragma: no cover
    '''
    Make a pattern that matches the given SQLite3 databases. The databases are supplied as a
    sequence of configuration dicts, as per the configuration schema.
    '''
    return dump.make_database_dump_filename(make_dump_path(config), name)


def restore_database_dump(
    databases_config, config, log_prefix, database_name, dry_run, extract_process, connection_params
):
    '''
    Restore the given SQLite3 database from an extract stream. The databases are supplied as a
    sequence containing one dict describing each database (as per the configuration schema), but
    only the database corresponding to the given database name is restored. Use the given log prefix
    in any log entries. If this is a dry run, then don't actually restore anything. Trigger the
    given active extract process (an instance of subprocess.Popen) to produce output to consume.
    '''
    dry_run_label = ' (dry run; not actually restoring anything)' if dry_run else ''

    try:
        database = next(
            database_config
            for database_config in databases_config
            if database_config.get('name') == database_name
        )
    except StopIteration:
        raise ValueError(
            f'A database named "{database_name}" could not be found in the configuration'
        )

    database_path = connection_params['restore_path'] or database.get(
        'restore_path', database.get('path')
    )

    logger.debug(f'{log_prefix}: Restoring SQLite database at {database_path}{dry_run_label}')
    if dry_run:
        return

    try:
        os.remove(database_path)
        logger.warning(f'{log_prefix}: Removed existing SQLite database at {database_path}')
    except FileNotFoundError:  # pragma: no cover
        pass

    restore_command = (
        'sqlite3',
        database_path,
    )

    # Don't give Borg local path so as to error on warnings, as "borg extract" only gives a warning
    # if the restore paths don't exist in the archive.
    execute_command_with_processes(
        restore_command,
        [extract_process],
        output_log_level=logging.DEBUG,
        input_file=extract_process.stdout,
    )
