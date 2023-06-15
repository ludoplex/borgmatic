import borgmatic.commands.arguments
import borgmatic.commands.completion.actions


def parser_flags(parser):
    '''
    Given an argparse.ArgumentParser instance, return its argument flags in a space-separated
    string.
    '''
    return ' '.join(option for action in parser._actions for option in action.option_strings)


def bash_completion():
    '''
    Return a bash completion script for the borgmatic command. Produce this by introspecting
    borgmatic's command-line argument parsers.
    '''
    top_level_parser, subparsers = borgmatic.commands.arguments.make_parsers()
    global_flags = parser_flags(top_level_parser)

    # Avert your eyes.
    return '\n'.join(
        (
            'check_version() {',
            '    local this_script="$(cat "$BASH_SOURCE" 2> /dev/null)"',
            '    local installed_script="$(borgmatic --bash-completion 2> /dev/null)"',
            '    if [ "$this_script" != "$installed_script" ] && [ "$installed_script" != "" ];'
            f'''        then cat << EOF\n{borgmatic.commands.completion.actions.upgrade_message(
                    'bash',
                    'sudo sh -c "borgmatic --bash-completion > $BASH_SOURCE"',
                    '$BASH_SOURCE',
                )}\nEOF''',
            '    fi',
            '}',
            'complete_borgmatic() {',
        )
        + tuple(
            '''    if [[ " ${COMP_WORDS[*]} " =~ " %s " ]]; then
        COMPREPLY=($(compgen -W "%s %s %s" -- "${COMP_WORDS[COMP_CWORD]}"))
        return 0
    fi'''
            % (
                action,
                parser_flags(subparser),
                ' '.join(
                    borgmatic.commands.completion.actions.available_actions(subparsers, action)
                ),
                global_flags,
            )
            for action, subparser in reversed(subparsers.choices.items())
        )
        + (
            '    COMPREPLY=($(compgen -W "%s %s" -- "${COMP_WORDS[COMP_CWORD]}"))'  # noqa: FS003
            % (
                ' '.join(borgmatic.commands.completion.actions.available_actions(subparsers)),
                global_flags,
            ),
            '    (check_version &)',
            '}',
            '\ncomplete -o bashdefault -o default -F complete_borgmatic borgmatic',
        )
    )
