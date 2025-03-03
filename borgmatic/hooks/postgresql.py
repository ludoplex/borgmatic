import csv
import itertools
import logging
import os
import shlex

from borgmatic.execute import (
    execute_command,
    execute_command_and_capture_output,
    execute_command_with_processes,
)
from borgmatic.hooks import dump

logger = logging.getLogger(__name__)


def make_dump_path(config):  # pragma: no cover
    '''
    Make the dump path from the given configuration dict and the name of this hook.
    '''
    return dump.make_database_dump_path(
        config.get('borgmatic_source_directory'), 'postgresql_databases'
    )


def make_extra_environment(database, restore_connection_params=None):
    '''
    Make the extra_environment dict from the given database configuration.
    If restore connection params are given, this is for a restore operation.
    '''
    extra = dict()

    try:
        if restore_connection_params:
            extra['PGPASSWORD'] = restore_connection_params.get('password') or database.get(
                'restore_password', database['password']
            )
        else:
            extra['PGPASSWORD'] = database['password']
    except (AttributeError, KeyError):
        pass

    extra['PGSSLMODE'] = database.get('ssl_mode', 'disable')
    if 'ssl_cert' in database:
        extra['PGSSLCERT'] = database['ssl_cert']
    if 'ssl_key' in database:
        extra['PGSSLKEY'] = database['ssl_key']
    if 'ssl_root_cert' in database:
        extra['PGSSLROOTCERT'] = database['ssl_root_cert']
    if 'ssl_crl' in database:
        extra['PGSSLCRL'] = database['ssl_crl']
    return extra


EXCLUDED_DATABASE_NAMES = ('template0', 'template1')


def database_names_to_dump(database, extra_environment, log_prefix, dry_run):
    '''
    Given a requested database config, return the corresponding sequence of database names to dump.
    In the case of "all" when a database format is given, query for the names of databases on the
    configured host and return them. For "all" without a database format, just return a sequence
    containing "all".
    '''
    requested_name = database['name']

    if requested_name != 'all':
        return (requested_name,)
    if not database.get('format'):
        return ('all',)
    if dry_run:
        return ()

    psql_command = shlex.split(database.get('psql_command') or 'psql')
    list_command = (
        tuple(psql_command)
        + ('--list', '--no-password', '--no-psqlrc', '--csv', '--tuples-only')
        + (('--host', database['hostname']) if 'hostname' in database else ())
        + (('--port', str(database['port'])) if 'port' in database else ())
        + (('--username', database['username']) if 'username' in database else ())
        + (tuple(database['list_options'].split(' ')) if 'list_options' in database else ())
    )
    logger.debug(f'{log_prefix}: Querying for "all" PostgreSQL databases to dump')
    list_output = execute_command_and_capture_output(
        list_command, extra_environment=extra_environment
    )

    return tuple(
        row[0]
        for row in csv.reader(list_output.splitlines(), delimiter=',', quotechar='"')
        if row[0] not in EXCLUDED_DATABASE_NAMES
    )


def dump_databases(databases, config, log_prefix, dry_run):
    '''
    Dump the given PostgreSQL databases to a named pipe. The databases are supplied as a sequence of
    dicts, one dict describing each database as per the configuration schema. Use the given
    configuration dict to construct the destination path and the given log prefix in any log
    entries.

    Return a sequence of subprocess.Popen instances for the dump processes ready to spew to a named
    pipe. But if this is a dry run, then don't actually dump anything and return an empty sequence.

    Raise ValueError if the databases to dump cannot be determined.
    '''
    dry_run_label = ' (dry run; not actually dumping anything)' if dry_run else ''
    processes = []

    logger.info(f'{log_prefix}: Dumping PostgreSQL databases{dry_run_label}')

    for database in databases:
        extra_environment = make_extra_environment(database)
        dump_path = make_dump_path(config)
        dump_database_names = database_names_to_dump(
            database, extra_environment, log_prefix, dry_run
        )

        if not dump_database_names:
            if dry_run:
                continue

            raise ValueError('Cannot find any PostgreSQL databases to dump.')

        for database_name in dump_database_names:
            dump_format = database.get('format', None if database_name == 'all' else 'custom')
            default_dump_command = 'pg_dumpall' if database_name == 'all' else 'pg_dump'
            dump_command = database.get('pg_dump_command') or default_dump_command
            dump_filename = dump.make_database_dump_filename(
                dump_path, database_name, database.get('hostname')
            )
            if os.path.exists(dump_filename):
                logger.warning(
                    f'{log_prefix}: Skipping duplicate dump of PostgreSQL database "{database_name}" to {dump_filename}'
                )
                continue

            command = (
                (
                    dump_command,
                    '--no-password',
                    '--clean',
                    '--if-exists',
                )
                + (('--host', database['hostname']) if 'hostname' in database else ())
                + (('--port', str(database['port'])) if 'port' in database else ())
                + (('--username', database['username']) if 'username' in database else ())
                + (('--no-owner',) if database.get('no_owner', False) else ())
                + (('--format', dump_format) if dump_format else ())
                + (('--file', dump_filename) if dump_format == 'directory' else ())
                + (tuple(database['options'].split(' ')) if 'options' in database else ())
                + (() if database_name == 'all' else (database_name,))
                # Use shell redirection rather than the --file flag to sidestep synchronization issues
                # when pg_dump/pg_dumpall tries to write to a named pipe. But for the directory dump
                # format in a particular, a named destination is required, and redirection doesn't work.
                + (('>', dump_filename) if dump_format != 'directory' else ())
            )

            logger.debug(
                f'{log_prefix}: Dumping PostgreSQL database "{database_name}" to {dump_filename}{dry_run_label}'
            )
            if dry_run:
                continue

            if dump_format == 'directory':
                dump.create_parent_directory_for_dump(dump_filename)
                execute_command(
                    command,
                    shell=True,
                    extra_environment=extra_environment,
                )
            else:
                dump.create_named_pipe_for_dump(dump_filename)
                processes.append(
                    execute_command(
                        command,
                        shell=True,
                        extra_environment=extra_environment,
                        run_to_completion=False,
                    )
                )

    return processes


def remove_database_dumps(databases, config, log_prefix, dry_run):  # pragma: no cover
    '''
    Remove all database dump files for this hook regardless of the given databases. Use the given
    configuration dict to construct the destination path and the log prefix in any log entries. If
    this is a dry run, then don't actually remove anything.
    '''
    dump.remove_database_dumps(make_dump_path(config), 'PostgreSQL', log_prefix, dry_run)


def make_database_dump_pattern(databases, config, log_prefix, name=None):  # pragma: no cover
    '''
    Given a sequence of configurations dicts, a configuration dict, a prefix to log with, and a
    database name to match, return the corresponding glob patterns to match the database dump in an
    archive.
    '''
    return dump.make_database_dump_filename(make_dump_path(config), name, hostname='*')


def restore_database_dump(
    databases_config, config, log_prefix, database_name, dry_run, extract_process, connection_params
):
    '''
    Restore the given PostgreSQL database from an extract stream. The databases are supplied as a
    sequence containing one dict describing each database (as per the configuration schema), but
    only the database corresponding to the given database name is restored. Use the given
    configuration dict to construct the destination path and the given log prefix in any log
    entries. If this is a dry run, then don't actually restore anything. Trigger the given active
    extract process (an instance of subprocess.Popen) to produce output to consume.

    If the extract process is None, then restore the dump from the filesystem rather than from an
    extract stream.

    Use the given connection parameters to connect to the database. The connection parameters are
    hostname, port, username, and password.
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

    hostname = connection_params['hostname'] or database.get(
        'restore_hostname', database.get('hostname')
    )
    port = str(connection_params['port'] or database.get('restore_port', database.get('port', '')))
    username = connection_params['username'] or database.get(
        'restore_username', database.get('username')
    )

    all_databases = bool(database['name'] == 'all')
    dump_filename = dump.make_database_dump_filename(
        make_dump_path(config), database['name'], database.get('hostname')
    )
    psql_command = shlex.split(database.get('psql_command') or 'psql')
    analyze_command = (
        tuple(psql_command)
        + ('--no-password', '--no-psqlrc', '--quiet')
        + (('--host', hostname) if hostname else ())
        + (('--port', port) if port else ())
        + (('--username', username) if username else ())
        + (('--dbname', database['name']) if not all_databases else ())
        + (tuple(database['analyze_options'].split(' ')) if 'analyze_options' in database else ())
        + ('--command', 'ANALYZE')
    )
    use_psql_command = all_databases or database.get('format') == 'plain'
    pg_restore_command = shlex.split(database.get('pg_restore_command') or 'pg_restore')
    restore_command = (
        tuple(psql_command if use_psql_command else pg_restore_command)
        + ('--no-password',)
        + (('--no-psqlrc',) if use_psql_command else ('--if-exists', '--exit-on-error', '--clean'))
        + (('--dbname', database['name']) if not all_databases else ())
        + (('--host', hostname) if hostname else ())
        + (('--port', port) if port else ())
        + (('--username', username) if username else ())
        + (('--no-owner',) if database.get('no_owner', False) else ())
        + (tuple(database['restore_options'].split(' ')) if 'restore_options' in database else ())
        + (() if extract_process else (dump_filename,))
        + tuple(
            itertools.chain.from_iterable(('--schema', schema) for schema in database['schemas'])
            if database.get('schemas')
            else ()
        )
    )

    extra_environment = make_extra_environment(
        database, restore_connection_params=connection_params
    )

    logger.debug(f"{log_prefix}: Restoring PostgreSQL database {database['name']}{dry_run_label}")
    if dry_run:
        return

    # Don't give Borg local path so as to error on warnings, as "borg extract" only gives a warning
    # if the restore paths don't exist in the archive.
    execute_command_with_processes(
        restore_command,
        [extract_process] if extract_process else [],
        output_log_level=logging.DEBUG,
        input_file=extract_process.stdout if extract_process else None,
        extra_environment=extra_environment,
    )
    execute_command(analyze_command, extra_environment=extra_environment)
