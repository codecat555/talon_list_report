# This module provides a mechanism for overriding talon lists and commands via a set of csv files.

import os
from pathlib import Path
# import pprint
from typing import Any, List, Dict, Tuple, Callable
import logging
import re
import tempfile

from talon import Context, registry, app, Module, actions, ui

# enable/disable debug messages
testing = False

mod = Module()
ctx = Context()

def get_source_file_paths(context_path: str) -> List[str]:
    """Function for extracting filesystem path information from the context path string."""
    
    if not context_path.startswith('user.'):
        raise ValueError(f'get_source_file_paths: can only handle user-defined contexts ({context_path})')

    sub_path = Path(re.sub(r'^user\.', '', context_path).replace('.', os.path.sep))
    parent_path = actions.path.talon_user() / sub_path.parents[0]
    
    # if testing:
    #     logging.debug(f'get_source_file_paths: {context_path=}, {sub_path=}, {parent_path=}')
    
    user_paths = []
    if context_path.endswith('.talon'):
        # there is a special case here: when the given context path refers to a file
        # named 'talon.py', as in 'knausj_talon/lang/talon/talon.py'.

        talon_file_path = parent_path.with_suffix('.talon')
        python_file_path = actions.path.talon_user() / sub_path.with_suffix('.py')
        # logging.debug(f'get_source_file_paths: {talon_file_path=}, {python_file_path=}')

        if parent_path.is_dir() and python_file_path.exists():
            user_paths.append(str(python_file_path))

        if talon_file_path.exists():
            user_paths.append(str(talon_file_path))

    else:
        python_file_path = actions.path.talon_user() / sub_path.with_suffix('.py')
        if python_file_path.exists():
            user_paths.append(str(python_file_path))

    # if testing:
    #     logging.debug(f'get_source_file_paths: {user_paths}')
    
    return user_paths
            
def parse_talon_file_for_capture_refs(context_path: str, list_name: str) -> Dict[str, List[str]]:
    """Internal method to extract capture references from the source file for the given context_path."""

    file_paths = get_source_file_paths(context_path)
    
    refs = {}
    for file_path in file_paths:
        capture_refs = []
        with open(file_path, 'r') as f:
            seen_dash = False
            for line in f:
                if line.strip().startswith('tag():'):
                    continue

                command = line.split(':')[0]
                if capture_list_ref in command:
                    capture_refs.append(command)
                        
                if not seen_dash:
                    if line.startswith('-'):
                        seen_dash = True

                        # anything we've accumulated so far is junk, start over
                        capture_refs = []
                    elif line.lstrip().startswith('#'):
                        continue
                    
        if capture_refs:
            refs[file_path] = capture_refs

    # logging.debug(f'_parse_talon_file_for_capture_refs: for {ctx_path}, returning {source_match_string=}, {capture_refs=}')
    
    return refs

def contains_list_reference(list_name: str, rule: str) -> bool:
    """Predicate for checking presence of a reference to the given list in the given rule."""
    # fix up rule
    user_rule = re.sub(r'\bself\.', 'user.', rule)
    
    list_ref_pat = '{' + list_name + '}'
    capture_list_ref_pat = '<' + list_name + '>'
    
    result = list_ref_pat in user_rule or capture_list_ref_pat in user_rule
    
    # logging.debug(f'contains_list_reference: {list_name=}, {rule=}, {user_rule=} ==> {result=}')
    
    return result

def _discover_list(list_name: str) -> Dict[str, Dict]:
    """Accumulate data about the given list and return it."""

    # Note: first, we scan the registry contexts and then we scan registry.commands
    # and registry.captures...else we don't get all the information because some
    # contexts may not be active.
    list_data = {}
    for context_path, context in registry.contexts.items():
        if list_name in context.lists.keys():
            # found a matching context

            if not 'defines' in list_data:
                # initialize defines
                list_data['defines'] = []

            # capture the fact that this context (re-)defines the list
            list_data['defines'].append(context_path)

        # scan the *context* commands for references to the list
        if context_path.endswith('.talon'):
            # commands = [v for v in context.commands.values() if list_ref in v.rule.rule or capture_list_ref in v.rule.rule]
            commands = [v for v in context.commands.values() if contains_list_reference(list_name, v.rule.rule)]
            if commands:
                if not 'commands' in list_data:
                    list_data['commands'] = {}
                if not context_path in list_data['commands']:
                    list_data['commands'][context_path] = set()
                for command in commands:
                    list_data['commands'][context_path].add(command)
            
    # scan the *registry* commands for references to the list
    for v in registry.commands.values():
        rule = v[0].rule.rule
        # if list_ref in rule or capture_list_ref in rule:
        if contains_list_reference(list_name, rule):
            # found matching command
            
            if not 'commands' in list_data:
                # initialize commands
                list_data['commands'] = {}
                
            context_path = v[0].rule.ref.path
            if not context_path in list_data['commands']:
                # initialize commands for this context
                list_data['commands'][context_path] = set()
                
            list_data['commands'][context_path].add(v[0])

    # scan the registry captures for references to the list
    for v in registry.captures.values():
        rule = v[0].rule.rule
            
        if contains_list_reference(list_name, rule):
            # found matching capture
            
            if 'position' in rule:
                logging.debug(f'OKE DONKEY: {list_ref=}, {v[0]=}')
            
            if not 'captures' in list_data:
                # initialize captures
                list_data['captures'] = {}
                
            context_path = v[0].rule.ref.path
            if not context_path in list_data['captures']:
                # initialize captures for this context
                list_data['captures'][context_path] = set()
                
            list_data['captures'][context_path].add(v[0])

    return list_data

def _generate_list_report(list_data: Dict) -> str:
    handle, path = tempfile.mkstemp(suffix='.txt', text=True)
    with os.fdopen(handle, "w") as fp:
        # pp = pprint.PrettyPrinter(indent=4)
        # print(pp.pformat(list_data), file=fp)
        first_loop = True
        for list_name, list_data in list_data.items():
            if first_loop:
                first_loop = False
            else:
                print(f'----\n\n', file=fp)
                
            print(f'Talon List Report for "{list_name}"\n', file=fp)
            
            if not list_data:
                print(f'--> NO REFERENCES FOUND FOR THIS LIST\n\n', file=fp)
                continue
                
            if 'defines' in list_data:
                print(f'* The list is defined in the following modules/contexts:\n', file=fp)
                for context_path in list_data['defines']:
                    file_paths = ','.join(get_source_file_paths(context_path))
                    print(f'    {context_path} ({file_paths})', file=fp)
                print('\n', file=fp)
                
            if 'captures' in list_data:
                print(f'* The list is referenced in the following capture rules:\n', file=fp)
                for context_path, captures in list_data['captures'].items():
                    file_paths = ','.join(get_source_file_paths(context_path))
                    print(f'    Context: {context_path} ({file_paths})', file=fp)
                    for capture in captures:
                        print(f'        Path: {capture.path} ==> Rule: {capture.rule.rule}', file=fp)
                    print('\n', file=fp)

            if 'commands' in list_data:
                print(f'* The list is referenced by the following commands:\n', file=fp)
                for context_path, commands in list_data['commands'].items():
                    file_paths = ','.join(get_source_file_paths(context_path))
                    print(f'    Context: {context_path} ({file_paths})', file=fp)
                    for command in commands:
                        print(f'        {command.rule.rule}', file=fp)
                    print('\n', file=fp)

        return path

def _open_file(path: str) -> None:
    """Open the given file in the default application."""
    
    if app.platform == "windows":
        os.startfile(path, 'open')
    elif app.platform == "mac":
        ui.launch(path='/usr/bin/open', args=[str(path)])
    elif app.platform == "linux":
        ui.launch(path='/usr/bin/xdg-open', args=[str(path)])
    else:
        raise Exception(f'unknown system: {app.platform}')

@mod.action_class
class PersonalizationActions:
    """
    Commands for generating talon list reports
    """
    def show_talon_list_report(key_phrase: str) -> None:
        "Generate a basic report showing information about any lists which (partially) match the given key phrase."

        # gather matching lists
        lists = [l for l in registry.lists.keys() if key_phrase in l]
        if not lists:
            app.notify(f'No lists found matching {key_phrase}.')
            return

        # gather data about the matching lists
        data = {}
        for list_name in lists:
            is_simple_list = all([k == v for k,v in registry.lists[list_name][0].items()])

            # scan the registry contexts for definitions of the list and for commands that reference the list.
            list_data = _discover_list(list_name)

            # save the accumulated data for this list
            data[list_name] = list_data

        # print report to a temp file
        path = _generate_list_report(data)

        # open the temp file using default app
        _open_file(path)
