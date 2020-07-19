#!/usr/bin/env python3
import os
import json
import shutil
import sys

import mmpm.color
import mmpm.utils
import mmpm.consts
import mmpm.models

from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from collections import defaultdict
from typing import List, Dict, Tuple


MagicMirrorPackage = mmpm.models.MagicMirrorPackage
get_env = mmpm.utils.get_env

def database_details(packages: Dict[str, List[MagicMirrorPackage]]) -> None:
    '''
    Displays information regarding the most recent database file, ie. when it
    was taken, when the next scheduled database retrieval will be taken, how many module
    categories exist, and the total number of modules available. Additionally,
    tells user how to forcibly request the database be updated.

    Parameters:
        packages (Dict[str, List[MagicMirrorPackage]]): Dictionary of MagicMirror modules

    Returns:
        None
    '''

    import datetime

    num_categories: int = len(packages)
    num_packages: int = 0

    creation_unix_timestamp, expiration_unix_timestamp = mmpm.utils.calculation_expiration_date_of_database()
    creation_date = datetime.datetime.fromtimestamp(int(creation_unix_timestamp))
    expiration_date = datetime.datetime.fromtimestamp(int(expiration_unix_timestamp))

    for category in packages.values():
        num_packages += len(category)

    print(mmpm.color.normal_green('Last updated:'), f'{creation_date}')
    print(mmpm.color.normal_green('Next scheduled update:'), f'{expiration_date}')
    print(mmpm.color.normal_green('Package categories:'), f'{num_categories}')
    print(mmpm.color.normal_green('Packages available:'), f'{num_packages}')


def check_for_mmpm_updates(gui=False, automated=False) -> bool:
    '''
    Scrapes the main file of MMPM off the github repo, and compares the current
    version, versus the one available in the master branch. If there is a newer
    version, the user is prompted for an upgrade.

    Parameters:
        None

    Returns:
        bool: True on success, False on failure
    '''
    import mmpm.mmpm # pylint: disable=redefined-outer-name

    try:
        cyan_application: str = f"{mmpm.color.normal_cyan('application')}"
        mmpm.utils.log.info(f'Checking for newer version of MMPM. Current version: {mmpm.mmpm.__version__}')
        if automated:
            message: str = f"Checking {mmpm.color.normal_green('MMPM')} [{cyan_application}] ({mmpm.color.normal_magenta('automated')}) for updates"
        else:
            message = f"Checking {mmpm.color.normal_green('MMPM')} [{cyan_application}] for updates"
        mmpm.utils.plain_print(message)

        try:
            # just to keep the console output the same as all other update commands
            error_code, contents, _ = mmpm.utils.run_cmd(['curl', mmpm.consts.MMPM_FILE_URL])
        except KeyboardInterrupt:
            mmpm.utils.keyboard_interrupt_log()

        if error_code:
            mmpm.utils.fatal_msg('Failed to retrieve MMPM version number')

    except (HTTPError, URLError) as error:
        print(mmpm.consts.RED_X)
        mmpm.utils.error_msg(str(error))
        return False

    from re import findall
    version_number: float = float(findall(r"\d+\.\d+", findall(r"__version__ = \d+\.\d+", contents)[0])[0])
    print(mmpm.consts.GREEN_CHECK_MARK)

    if not version_number:
        mmpm.utils.fatal_msg('No version number found on MMPM repository')

    if mmpm.mmpm.__version__ >= version_number:
        mmpm.utils.log.info(f'No newer version of MMPM found > {version_number} available. The current version is the latest')
        return False

    mmpm.utils.log.info(f'Found newer version of MMPM: {version_number}')
    upgrades, _ = get_available_upgrades()

    with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'w') as available_upgrades:
        upgrades[mmpm.consts.MMPM] = True
        json.dump(upgrades, available_upgrades)

    if gui:
        mmpm.utils.log.info('A newer version of MMPM was detected via the GUI')
        print(f"A newer version of MMPM is available ({version_number}). Please upgrade via terminal using 'mmpm uprade --mmpm")
        return True

    return True


def upgrade_mmpm() -> str:

    mmpm.utils.log.info('User chose to update MMPM')

    print(f"{mmpm.consts.GREEN_PLUS} Upgrading {mmpm.color.normal_green('MMPM')}")
    os.system('rm -rf /tmp/mmpm')
    os.chdir(os.path.join('/', 'tmp'))

    error_code, _, stderr = mmpm.utils.clone('mmpm', mmpm.consts.MMPM_REPO_URL)

    if error_code:
        mmpm.utils.error_msg(stderr)
        return stderr

    os.chdir('/tmp/mmpm')

    # if the user needs to be prompted for their password, this can't be a subprocess
    os.system('make reinstall')
    return ''


def upgrade_package(package: MagicMirrorPackage) -> str:
    '''
    Depending on flags passed in as arguments:

    Checks for available package updates, and alerts the user. Or, pulls latest
    version of module(s) from the associated repos.

    If upgrading, a user can upgrade all modules that have available upgrades
    by ommitting additional arguments. Or, upgrade specific modules by
    supplying their case-sensitive name(s) as an addtional argument.

    Parameters:
        package (MagicMirrorPackage): the MagicMirror module being upgraded

    Returns:
        stderr (str): the resulting error message of the upgrade. If the message is zero length, it was successful
    '''

    os.chdir(package.directory)

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} Performing upgrade for {mmpm.color.normal_green(package.title)}')
    error_code, _, stderr = mmpm.utils.run_cmd(["git", "pull"])

    if error_code:
        mmpm.utils.error_msg(f'Failed to upgrade MagicMirror {mmpm.consts.RED_X}')
        mmpm.utils.error_msg(stderr)
        return stderr

    else:
        print(mmpm.consts.GREEN_CHECK_MARK)

    stderr = mmpm.utils.install_dependencies(package.directory)

    if stderr:
        print(mmpm.consts.RED_X)
        mmpm.utils.error_msg(stderr)
        return stderr

    return ''


def upgrade_available(assume_yes: bool = False, selection: List[str] = []) -> bool:
    confirmed: dict = {mmpm.consts.PACKAGES: [], mmpm.consts.MMPM: False, mmpm.consts.MAGICMIRROR: False}
    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))
    upgrades = get_available_upgrades()
    upgraded: bool = False

    has_upgrades: bool = False
    mmpm_selected: bool = False
    magicmirror_selected: bool = False
    user_selections: bool = bool(selection)

    for key in upgrades[MMPM_MAGICMIRROR_ROOT]:
        if upgrades[MMPM_MAGICMIRROR_ROOT][key]:
            has_upgrades = True
            break

    if not has_upgrades and not upgrades[mmpm.consts.MMPM]:
        print(f'No upgrades available {mmpm.consts.YELLOW_X}')

    if upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES]:
        if selection:
            valid_pkgs: List[MagicMirrorPackage] = [pkg for pkg in upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES] if pkg.title in selection]

            for pkg in upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES]:
                if pkg.title in selection:
                    valid_pkgs.append(pkg)
                    selection.remove(pkg.title)

            if mmpm.consts.MMPM in selection and upgrades[mmpm.consts.MMPM]:
                    mmpm_selected = True
                    selection.remove(mmpm.consts.MMPM)

            if mmpm.consts.MAGICMIRROR in selection and upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.MAGICMIRROR]:
                    magicmirror_selected = True
                    selection.remove(mmpm.consts.MAGICMIRROR)

            if selection: # the left overs that weren't matched
                mmpm.utils.error_msg(f'Unable to match {selection} to a package/application with available upgrades')

            for package in valid_pkgs:
                if package.title in selection and mmpm.utils.prompt_user(f'Upgrade {mmpm.color.normal_green(package.title)} ({package.repository}) now?', assume_yes=assume_yes):
                    confirmed[mmpm.consts.PACKAGES].append(package)
        else:
            for package in upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES]:
                if mmpm.utils.prompt_user(f'Upgrade {mmpm.color.normal_green(package.title)} ({package.repository}) now?', assume_yes=assume_yes):
                    confirmed[mmpm.consts.PACKAGES].append(package)

    if upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.MAGICMIRROR] and magicmirror_selected or not user_selections:
        confirmed[mmpm.consts.MAGICMIRROR] = mmpm.utils.prompt_user(f"Upgrade {mmpm.color.normal_green('MagicMirror')} now?", assume_yes=assume_yes)

    if upgrades[mmpm.consts.MMPM] and mmpm_selected or not user_selections:
        confirmed[mmpm.consts.MMPM] = mmpm.utils.prompt_user(f"Upgrade {mmpm.color.normal_green('MMPM')} now?", assume_yes=assume_yes)

    for pkg in confirmed[mmpm.consts.PACKAGES]:
        error = upgrade_package(pkg)

        if error:
            mmpm.utils.error_msg(error)
            continue

        upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES].remove(pkg)
        upgraded = True

    if confirmed[mmpm.consts.MMPM]:
        error = upgrade_mmpm()
        if error:
            mmpm.utils.error_msg(f'{error} {mmpm.consts.RED_X}')
        else:
            upgrades[mmpm.consts.MMPM] = False
            upgraded = True

    if confirmed[mmpm.consts.MAGICMIRROR]:
        error = upgrade_magicmirror()

        if error:
            mmpm.utils.error_msg(error)
        else:
            upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.MAGICMIRROR] = False
            upgraded = True

    upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES] = [pkg.serialize_full() for pkg in upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES]]

    with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'w') as available_upgrades:
        json.dump(upgrades, available_upgrades)

    if upgraded and mmpm.utils.is_magicmirror_running():
        print('Restart MagicMirror for the changes to take effect')

    return True


def check_for_package_updates(packages: Dict[str, List[MagicMirrorPackage]]) -> List[MagicMirrorPackage]:
    '''
    Depending on flags passed in as arguments:

    Checks for available module updates, and alerts the user. Or, pulls latest
    version of module(s) from the associated repos.

    If upgrading, a user can upgrade all modules that have available upgrades
    by ommitting additional arguments. Or, upgrade specific modules by
    supplying their case-sensitive name(s) as an addtional argument.

    Parameters:
        packages (Dict[str, List[MagicMirrorPackage]]): Dictionary of MagicMirror modules

    Returns:
        upgradeable (List[MagicMirrorPackage]): the list of packages that have available upgrades
    '''

    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))
    MAGICMIRROR_MODULES_DIR: str = os.path.normpath(os.path.join(MMPM_MAGICMIRROR_ROOT, 'modules'))

    os.chdir(MAGICMIRROR_MODULES_DIR)
    installed_packages: Dict[str, List[MagicMirrorPackage]] = get_installed_packages(packages)
    any_installed: bool = False

    for category in installed_packages:
        if installed_packages[category]:
            any_installed = True
            break

    if not any_installed:
        # asserting the available-updates file doesn't contain any artifacts of
        # previously installed packages that had updates at one point in time
        if not mmpm.utils.reset_available_upgrades_for_environment(MMPM_MAGICMIRROR_ROOT):
            mmpm.utils.log.error('Failed to reset available upgrades for the current environment. File has been recreated')
            os.system(f'rm -f {mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE}; touch {mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE}')
        return []

    upgradeable: List[MagicMirrorPackage] = []
    cyan_package: str = f"{mmpm.color.normal_cyan('package')}"

    for _, _packages in installed_packages.items():
        for package in _packages:
            os.chdir(package.directory)

            mmpm.utils.plain_print(f'Checking {mmpm.color.normal_green(package.title)} [{cyan_package}] for updates')

            try:
                error_code, _, stdout = mmpm.utils.run_cmd(['git', 'fetch', '--dry-run'])

            except KeyboardInterrupt:
                print(mmpm.consts.RED_X)
                mmpm.utils.keyboard_interrupt_log()

            if error_code:
                print(mmpm.consts.RED_X)
                mmpm.utils.error_msg('Unable to communicate with git server')
                continue

            if stdout:
                upgradeable.append(package)

            print(mmpm.consts.GREEN_CHECK_MARK)

    upgrades: dict = get_available_upgrades()

    with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'w') as available_upgrades:
        if MMPM_MAGICMIRROR_ROOT not in upgrades:
            upgrades[MMPM_MAGICMIRROR_ROOT] = {mmpm.consts.PACKAGES: [], mmpm.consts.MAGICMIRROR: False}

        upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES] = [pkg.serialize_full() for pkg in upgradeable]
        json.dump(upgrades, available_upgrades)

    return upgradeable


def search_packages(packages: Dict[str, List[MagicMirrorPackage]], query: str, case_sensitive: bool = False, by_title_only: bool = False) -> dict:
    '''
    Used to search the 'modules' for either a category, or keyword/phrase
    appearing within module descriptions. If the argument supplied is a
    category name, all modules from that category will be listed. Otherwise,
    all modules whose descriptions contain the keyword/phrase will be
    displayed.

    Parameters:
        packages (Dict[str, List[MagicMirrorPackage]]): Dictionary of MagicMirror modules
        query (str): user provided search string
        case_sensitive (bool): if True, the query's exact casing is used in search
        by_title_only (bool): if True, only the title is considered when matching packages to query

    Returns:
        dict
    '''

    # if the query matches one of the category names exactly, return everything in that category
    if query in packages:
        return {query: packages[query]}

    search_results: Dict[str, List[MagicMirrorPackage]] = defaultdict(list)

    if by_title_only:
        match = lambda query, pkg: query == pkg.title
    elif case_sensitive:
        match = lambda query, pkg: query in pkg.description or query in pkg.title or query in pkg.author
    else:
        query = query.lower()
        match = lambda query, pkg: query in pkg.description.lower() or query in pkg.title.lower() or query in pkg.author.lower()

    for category, _packages in packages.items():
        search_results[category] = [package for package in _packages if match(query, package)]

    return search_results


def show_package_details(packages: Dict[str, List[MagicMirrorPackage]], verbose: bool) -> None:
    '''
    Displays more detailed information that presented in normal search results.
    The output is formatted similarly to the output of the Debian/Ubunut 'apt' CLI

    Parameters:
        packages (List[defaultdict]): List of Categorized MagicMirror packages

    Returns:
        None
    '''

    def __show_package__(category: str, package: MagicMirrorPackage) -> None:
        print(mmpm.color.normal_green(package.title))
        print(f'  Category: {category}')
        print(f'  Repository: {package.repository}')
        print(f'  Author: {package.author}')

    from textwrap import fill, indent

    if not verbose:
        def __show_details__(packages: dict) -> None:
            for category, _packages  in packages.items():
                for package in _packages:
                    __show_package__(category, package)
                    print(indent(fill(f'Description: {package.description}\n', width=80), prefix='  '), '\n')

    else:
        def __show_details__(packages: dict) -> None:
            for category, _packages  in packages.items():
                for package in _packages:
                    __show_package__(category, package)
                    for key, value in mmpm.utils.get_remote_package_details(package).items():
                        print(f"  {key}: {value}")
                    print(indent(fill(f'Description: {package.description}\n', width=80), prefix='  '), '\n')

    __show_details__(packages)


def get_installation_candidates(packages: Dict[str, List[MagicMirrorPackage]], packages_to_install: List[str]) -> List[MagicMirrorPackage]:
    '''
    Used to display more detailed information that presented in normal search results

    Parameters:
        packages (Dict[str, List[MagicMirrorPackage]]): MagicMirror modules database
        packages_to_install (List[str]): list of modules provided by user through command line arguments

    Returns:
        installation_candidates (List[MagicMirrorPackage]): list of modules whose module names match those of the modules_to_install
    '''

    installation_candidates: List[MagicMirrorPackage] = []

    for package_to_install in packages_to_install:
        found: bool = False
        for category in packages.values():
            for package in category:
                if package.title == package_to_install:
                    mmpm.utils.log.info(f'Matched {package.title} to installation candidate')
                    installation_candidates.append(package)
                    found = True
        if not found:
            mmpm.utils.error_msg(f"Unable to match package to query of '{package_to_install}'. Is there a typo?")

    return installation_candidates


def install_packages(installation_candidates: List[MagicMirrorPackage], assume_yes: bool = False) -> bool:
    '''
    Compares list of 'modules_to_install' to modules found within the
    'modules', clones the repository within the ~/MagicMirror/modules
    directory, and runs 'npm install' for each newly installed module.

    Parameters:
        installation_candidates (List[MagicMirrorPackage]): List of MagicMirrorPackages to install
        assume_yes (bool): if True, assume yes for user response, and do not display prompt

    Returns:
        bool: True upon success, False upon failure
    '''

    MAGICMIRROR_MODULES_DIR: str = os.path.normpath(os.path.join(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV), 'modules'))

    if not os.path.exists(MAGICMIRROR_MODULES_DIR):
        mmpm.utils.error_msg('MagicMirror directory not found. Please ensure the MMPM environment variables are set properly in your shell configuration')
        return False

    if not installation_candidates:
        mmpm.utils.error_msg('Unable to match query any to installation candidates')
        return False

    mmpm.utils.log.info(f'Changing into MagicMirror modules directory {MAGICMIRROR_MODULES_DIR}')
    os.chdir(MAGICMIRROR_MODULES_DIR)

    # a flag to check if any of the modules have been installed. Used for displaying a message later
    match_count: int = len(installation_candidates)
    print(mmpm.color.normal_cyan(f"Matched query to {match_count} {'package' if match_count == 1 else 'packages'}"))

    for index, candidate in enumerate(installation_candidates):
        if not mmpm.utils.prompt_user(f'Install {mmpm.color.normal_green(candidate.title)} ({candidate.repository})?', assume_yes=assume_yes):
            mmpm.utils.log.info(f'User not chose to install {candidate.title}')
            installation_candidates[index] = MagicMirrorPackage()
        else:
            mmpm.utils.log.info(f'User chose to install {candidate.title} ({candidate.repository})')

    existing_module_dirs: List[str] = mmpm.utils.get_existing_package_directories()
    starting_count: int = len(existing_module_dirs)

    for package in installation_candidates:
        if package == None: # the module may be empty due to the above for loop
            continue

        package.directory = os.path.join(MAGICMIRROR_MODULES_DIR, package.title)

        for existing_dir in existing_module_dirs:
            if package.directory == existing_dir:
                mmpm.utils.log.error(f'Conflict encountered. Found a package named {package.title} already at {package.directory}')
                mmpm.utils.error_msg(f'A module named {package.title} is already installed in {package.directory}. Please remove {package.title} first.')
                continue

        try:
            success, _ = install_package(package, assume_yes=assume_yes)

            if success:
                existing_module_dirs.append(package.title)

        except KeyboardInterrupt:
            mmpm.utils.log.info(f'Cleaning up cancelled installation path of {package.directory} before exiting')
            os.chdir(mmpm.consts.HOME_DIR)
            os.system(f"rm -rf '{package.directory}'")
            mmpm.utils.keyboard_interrupt_log()

    if len(existing_module_dirs) == starting_count:
        return False

    print('Run `mmpm open --config` to edit the configuration for newly installed modules')
    return True


def install_package(package: MagicMirrorPackage, assume_yes: bool = False) -> Tuple[bool, str]:
    '''
    Used to display more detailed information that presented in normal search results

    Parameters:
        package (MagicMirrorPackage): the MagicMirrorPackage to be installed
        assume_yes (bool): if True, all prompts are assumed to have a response of yes from the user

    Returns:
        installation_candidates (List[dict]): list of modules whose module names match those of the modules_to_install
    '''

    MAGICMIRROR_MODULES_DIR: str = os.path.normpath(os.path.join(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV), 'modules'))
    os.chdir(MAGICMIRROR_MODULES_DIR)

    print(f'{mmpm.consts.GREEN_PLUS} Installing {mmpm.color.normal_green(package.title)}')

    error_code, _, stderr = mmpm.utils.clone(
        package.title,
        package.repository,
        os.path.normpath(package.directory if package.directory else os.path.join(MAGICMIRROR_MODULES_DIR, package.title))
    )

    if error_code:
        print(mmpm.consts.RED_X)
        mmpm.utils.error_msg(stderr)
        return False, stderr

    print(mmpm.consts.GREEN_CHECK_MARK)
    error: str = mmpm.utils.install_dependencies(package.directory)
    os.chdir(MAGICMIRROR_MODULES_DIR)

    if error:
        mmpm.utils.error_msg(error)
        message: str = f"Failed to install {package.title} at '{package.directory}'"
        mmpm.utils.log.error(message)

        yes = mmpm.utils.prompt_user(
            f"{mmpm.color.bright_red('ERROR:')} Failed to install {package.title} at '{package.directory}'. Remove the directory?",
            assume_yes=assume_yes
        )

        if yes:
            message = f"User chose to remove {package.title} at '{package.directory}'"
            # just to make sure there aren't any errors in removing the directory
            os.system(f"rm -rf '{package.directory}'")
            print(f"{mmpm.consts.GREEN_PLUS} Removing '{package.directory}' {mmpm.consts.GREEN_CHECK_MARK}")
        else:
            message = f"Keeping {package.title} at '{package.directory}'"
            print(f'\n{message}\n')
            mmpm.utils.log.info(message)

        return False, error

    return True, str()


def check_for_magicmirror_updates() -> bool:
    '''
    Checks for updates available to the MagicMirror repository. Alerts user if an upgrade is available.

    Parameters:
        None

    Returns:
        bool: True upon success, False upon failure
    '''
    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))

    if not os.path.exists(MMPM_MAGICMIRROR_ROOT):
        mmpm.utils.error_msg('MagicMirror application directory not found. Please ensure the MMPM environment variables are set properly in your shell configuration')
        return False

    is_git: bool = True

    if not os.path.exists(os.path.join(MMPM_MAGICMIRROR_ROOT, '.git')):
        mmpm.utils.warning_msg('The MagicMirror root is not a git repo. If running MagicMirror as a Docker container, updates cannot be performed via mmpm.')
        is_git = False

    update_available: bool = False

    if is_git:
        os.chdir(MMPM_MAGICMIRROR_ROOT)
        cyan_application: str = f"{mmpm.color.normal_cyan('application')}"
        mmpm.utils.plain_print(f"Checking {mmpm.color.normal_green('MagicMirror')} [{cyan_application}] for updates")

        try:
            # stdout and stderr are flipped for git command output, because that totally makes sense
            # except now stdout doesn't even contain error messages...thanks git
            error_code, _, stdout = mmpm.utils.run_cmd(['git', 'fetch', '--dry-run'])
        except KeyboardInterrupt:
            print(mmpm.consts.RED_X)
            mmpm.utils.keyboard_interrupt_log()

        print(mmpm.consts.GREEN_CHECK_MARK)

        if error_code:
            mmpm.utils.error_msg('Unable to communicate with git server')

        if stdout:
            update_available = True

    upgrades: dict = {}

    with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'r') as available_upgrades:
        try:
            upgrades = json.load(available_upgrades)
        except json.JSONDecodeError:
            upgrades = {
                mmpm.consts.MMPM: False,
                MMPM_MAGICMIRROR_ROOT: {mmpm.consts.PACKAGES: [], mmpm.consts.MAGICMIRROR: update_available}
            }

    with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'w') as available_upgrades:
        if MMPM_MAGICMIRROR_ROOT not in upgrades:
            upgrades[MMPM_MAGICMIRROR_ROOT] = {mmpm.consts.PACKAGES: [], mmpm.consts.MAGICMIRROR: update_available}
        else:
            upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.MAGICMIRROR] = update_available

        json.dump(upgrades, available_upgrades)

    return update_available


def upgrade_magicmirror() -> str:
    '''
    Handles upgrade processs of MagicMirror by pulling changes from MagicMirror
    repo, and installing dependencies.

    Parameters:
        None

    Returns:
        error (str): empty string if succcessful, contains error message on failure

    '''
    print(f"{mmpm.consts.GREEN_PLUS} Upgrading {mmpm.color.normal_green('MagicMirror')}")

    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))

    os.chdir(MMPM_MAGICMIRROR_ROOT)
    error_code, _, stderr = mmpm.utils.run_cmd(['git', 'pull'], progress=False)

    if error_code:
        mmpm.utils.error_msg(f'Failed to upgrade MagicMirror {mmpm.consts.RED_X}')
        mmpm.utils.error_msg(stderr)
        return stderr

    error: str = mmpm.utils.install_dependencies(MMPM_MAGICMIRROR_ROOT)

    if error:
        mmpm.utils.error_msg(error)
        return error

    print('Upgrade complete! Restart MagicMirror for the changes to take effect')
    return ''


def install_magicmirror() -> bool:
    '''
    Installs MagicMirror. First checks if a MagicMirror installation can be
    found, and if one is found, prompts user to update the MagicMirror.
    Otherwise, searches for current version of NodeJS on the system. If one is
    found, the MagicMirror is then installed. If an old version of NodeJS is
    found, a newer version is installed before installing MagicMirror.

    Parameters:
        None

    Returns:
        bool: True upon succcess, False upon failure
    '''
    known_envs: List[str] = [env for env in get_available_upgrades() if env != 'mmpm']
    parent: str = mmpm.consts.HOME_DIR

    import pathlib

    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))

    if os.path.exists(MMPM_MAGICMIRROR_ROOT):
        mmpm.utils.warning_msg(f'MagicMirror appears to be installed already in {os.getcwd()}. Please provide a new destination for the MagicMirror installation')
        try:
            parent = os.path.abspath(
                os.path.normpath(
                    mmpm.utils.assert_valid_input("Absolute path to new installation location: ",
                        forbidden_responses=known_envs,
                        reason='matches a known MagicMirror environment')
                )
            )
        except KeyboardInterrupt:
            print()
            sys.exit(0)
    else:
        print(f'{mmpm.consts.GREEN_PLUS} Installing MagicMirror')
    if mmpm.utils.prompt_user(f"Use '{parent}' as the parent directory of the new MagicMirror installation?"):
        pathlib.Path(parent).mkdir(parents=True, exist_ok=True)
        os.chdir(parent)
    else:
        sys.exit(0)

    if not shutil.which('curl'):
        mmpm.utils.fatal_msg("'curl' command not found. Please install 'curl', then re-run mmpm install --magicmirror")

    os.chdir(parent)
    print(mmpm.color.normal_cyan(f'Installing MagicMirror in {parent}/MagicMirror ...'))
    os.system('bash -c "$(curl -sL https://raw.githubusercontent.com/sdetweil/MagicMirror_scripts/master/raspberry.sh)"')
    return True


def remove_packages(installed_packages: Dict[str, List[MagicMirrorPackage]], packages_to_remove: List[str], assume_yes: bool = False) -> bool:
    '''
    Gathers list of modules currently installed in the ~/MagicMirror/modules
    directory, and removes each of the modules from the folder, if modules are
    currently installed. Otherwise, the user is shown an error message alerting
    them no modules are currently installed.

    Parameters:
        installed_packages (Dict[str, List[MagicMirrorPackage]]): List of dictionary of MagicMirror packages
        modules_to_remove (list): List of modules to remove
        assume_yes (bool): if True, all prompts are assumed to have a response of yes from the user

    Returns:
        bool: True upon success, False upon failure
    '''

    cancelled_removal: List[str] = []
    marked_for_removal: List[str] = []

    MAGICMIRROR_MODULES_DIR: str = os.path.join(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV), 'modules')

    package_dirs: List[str] = os.listdir(MAGICMIRROR_MODULES_DIR)

    try:
        for _, packages in installed_packages.items():
            for package in packages:
                dir_name = os.path.basename(package.directory)
                if dir_name in package_dirs and dir_name in packages_to_remove:
                    prompt: str = f'Would you like to remove {mmpm.color.normal_green(package.title)} ({package.directory})?'
                    if mmpm.utils.prompt_user(prompt, assume_yes=assume_yes):
                        marked_for_removal.append(dir_name)
                        mmpm.utils.log.info(f'User marked {dir_name} for removal')
                    else:
                        cancelled_removal.append(dir_name)
                        mmpm.utils.log.info(f'User chose not to remove {dir_name}')
    except KeyboardInterrupt:
        mmpm.utils.keyboard_interrupt_log()

    for title in packages_to_remove:
        if title not in marked_for_removal and title not in cancelled_removal:
            mmpm.utils.error_msg(f"'{title}' is not installed")
            mmpm.utils.log.info(f"User attemped to remove {title}, but no module named '{title}' was found in {MAGICMIRROR_MODULES_DIR}")

    for dir_name in marked_for_removal:
        shutil.rmtree(dir_name)
        print(f'{mmpm.consts.GREEN_PLUS} Removed {mmpm.color.normal_green(dir_name)} {mmpm.consts.GREEN_CHECK_MARK}')
        mmpm.utils.log.info(f'Removed {dir_name}')

    if marked_for_removal:
        print('Run `mmpm open --config` to delete associated configurations of any removed modules')

    return True


def load_packages(force_refresh: bool = False) -> Dict[str, List[MagicMirrorPackage]]:
    '''
    Reads in modules from the hidden database file  and checks if the file is
    out of date. If so, the modules are gathered again from the MagicMirror 3rd
    Party Modules wiki.

    Parameters:
        force_refresh (bool): Boolean flag to force refresh of the database

    Returns:
        packages (Dict[str, List[MagicMirrorPackage]]): dictionary of MagicMirror 3rd party modules
    '''

    packages: dict = {}

    db_file: str = mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_DB_FILE
    db_exists: bool = os.path.exists(db_file) and bool(os.stat(db_file).st_size)
    ext_pkgs_file: str = mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE

    if db_exists:
        mmpm.utils.log.info(f'Backing up database file as {mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_DB_FILE}.bak')

        shutil.copyfile(
            mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_DB_FILE,
            f'{mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_DB_FILE}.bak'
        )

        mmpm.utils.log.info('Back up of database complete')

    # if the database has expired, or doesn't exist, get a new one
    if force_refresh or not db_exists:
        mmpm.utils.plain_print(
            f"{mmpm.consts.GREEN_PLUS} {'Refreshing' if db_exists else 'Initializing'} MagicMirror 3rd party packages database "
        )

        packages = retrieve_packages()

        if not packages:
            print(mmpm.consts.RED_X)
            mmpm.utils.error_msg(f'Failed to retrieve packages from {mmpm.consts.MAGICMIRROR_MODULES_URL}. Please check your internet connection.')

        # save the new database
        else:
            with open(db_file, 'w') as db:
                json.dump(packages, db, default=lambda pkg: pkg.serialize())

            print(mmpm.consts.GREEN_CHECK_MARK)

    if not packages and db_exists:
        with open(db_file, 'r') as db:
            packages = json.load(db)

            for category in packages:
                packages[category] = mmpm.utils.list_of_dict_to_list_of_magicmirror_packages(packages[category])

    if packages and os.path.exists(ext_pkgs_file) and bool(os.stat(ext_pkgs_file).st_size):
        packages.update(**load_external_packages())

    return packages


def load_external_packages() -> Dict[str, List[MagicMirrorPackage]]:
    '''
    Extracts the external packages from the JSON files stored in
    ~/.config/mmpm/mmpm-external-packages.json

    If no data is found, an empty list is returned

    Parameters:
        None

    Returns:
        external_packages (Dict[str, List[MagicMirrorPackage]]): the list of manually added MagicMirror packages
    '''
    external_packages: List[MagicMirrorPackage] = []

    try:
        with open(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE, 'r') as f:
            external_packages = mmpm.utils.list_of_dict_to_list_of_magicmirror_packages(json.load(f)[mmpm.consts.EXTERNAL_PACKAGES])
    except Exception:
        message = f'Failed to load data from {mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE}. Please examine the file, as it may be malformed and required manual corrective action.'
        mmpm.utils.warning_msg(message)

    return {mmpm.consts.EXTERNAL_PACKAGES: external_packages}

def retrieve_packages() -> Dict[str, List[MagicMirrorPackage]]:
    '''
    Scrapes the MagicMirror 3rd Party Wiki for all packages listed by community members

    Parameters:
        None

    Returns:
        packages (Dict[str, List[MagicMirrorPackage]]): dictionary of MagicMirror 3rd party modules
    '''

    packages: Dict[str, List[MagicMirrorPackage]] = defaultdict(list)

    try:
        url = urlopen(mmpm.consts.MAGICMIRROR_MODULES_URL)
        web_page = url.read()
    except (HTTPError, URLError):
        print(mmpm.consts.RED_X)
        mmpm.utils.fatal_msg('Unable to retrieve MagicMirror modules. Is your internet connection up?')
        return {}

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(web_page, 'html.parser')
    table_soup: list = soup.find_all('table')

    category_soup: list = soup.find_all(attrs={'class': 'markdown-body'})
    categories_soup: list = category_soup[0].find_all('h3')

    categories: list = []

    for index, _ in enumerate(categories_soup):
        last_element: object = len(categories_soup[index].contents) - 1
        new_category: object = categories_soup[index].contents[last_element]

        if new_category != 'General Advice':
            categories.append(new_category)

    tr_soup: list = []

    for table in table_soup:
        tr_soup.append(table.find_all("tr"))

    for index, row in enumerate(tr_soup):
        for column_number, _ in enumerate(row):
            # ignore cells that literally say "Title", "Author", "Description"
            if column_number > 0:
                td_soup: list = tr_soup[index][column_number].find_all('td')

                title: str = mmpm.consts.NOT_AVAILABLE
                repo: str = mmpm.consts.NOT_AVAILABLE
                author: str = mmpm.consts.NOT_AVAILABLE
                desc: str = mmpm.consts.NOT_AVAILABLE

                for idx, _ in enumerate(td_soup):
                    if idx == 0:
                        for td in td_soup[idx]:
                            title = td.contents[0]

                        for a in td_soup[idx].find_all('a'):
                            if a.has_attr('href'):
                                repo = a['href']

                        repo = str(repo)
                        title = mmpm.utils.sanitize_name(title)

                    elif idx == 1:
                        for contents in td_soup[idx].contents:
                            if type(contents).__name__ == 'Tag':
                                for tag in contents:
                                    author = tag.strip()
                            else:
                                author = contents

                        author = str(author)

                    else:
                        if contents:
                            desc = str()
                        for contents in td_soup[idx].contents:
                            if type(contents).__name__ == 'Tag':
                                for content in contents:
                                    desc += content.string
                            else:
                                desc += contents.string

                if title != mmpm.consts.MMPM:
                    # this is not very efficient, but it only runs once in a while
                    packages[categories[index]].append(
                        MagicMirrorPackage(
                            title=title.strip(),
                            author=author.strip(),
                            description=desc.strip(),
                            repository=repo.strip()
                        )
                    )

    return packages


def display_categories(packages: Dict[str, List[MagicMirrorPackage]], title_only: bool = False) -> None:
    '''
    Prints module category names and the total number of modules in one of two
    formats. The default is similar to the Debian apt package manager, and the
    prettified table alternative

    Parameters:
        packages (Dict[str, List[MagicMirrorPackage]]): list of dictionaries containing category names and module count

    Returns:
        None
    '''

    categories: List[dict] = [
        {
            mmpm.consts.CATEGORY: key,
            mmpm.consts.PACKAGES: len(packages[key])
        } for key in packages
    ]

    if title_only:
        for category in categories:
            print(category[mmpm.consts.CATEGORY])
        return

    for category in categories:
        print(
            mmpm.color.normal_green(category[mmpm.consts.CATEGORY]),
            f'\n  Packages: {category[mmpm.consts.PACKAGES]}\n'
        )


def display_packages(packages: Dict[str, List[MagicMirrorPackage]], title_only: bool = False, include_path: bool = False) -> None:
    '''
    Depending on the user flags passed in from the command line, either all
    existing packages may be displayed, or the names of all categories of
    packages may be displayed.

    Parameters:
        packages (Dict[str, List[MagicMirrorPackage]]): dictionary of MagicMirror 3rd party packages
        list_categories (bool): Boolean flag to list categories

    Returns:
        None
    '''
    format_description = lambda desc: desc[:MAX_LENGTH] + '...' if len(desc) > MAX_LENGTH else desc
    MAX_LENGTH: int = 120

    if title_only:
        _print_ = lambda package: print(package.title)

    elif include_path:
        _print_ = lambda package: print(
            mmpm.color.normal_green(f'{package.title}'),
            (f'\n  Directory: {package.directory}'),
            (f"\n  {format_description(package.description)}\n")
        )

    else:
        _print_ = lambda package: print(
            mmpm.color.normal_green(f'{package.title}'),
            (f"\n  {format_description(package.description)}\n")
        )

    for _, _packages in packages.items():
        for _, package in enumerate(_packages):
            _print_(package)


def display_available_upgrades() -> None:
    '''
    Based on the current environment, available upgrades for packages, and
    MagicMirror will be displayed. The status of upgrades available for MMPM is
    static, regardless of the environment. The available upgrades are read from
    a file, `~/.config/mmpm/mmpm-available-upgrades.json`, which is updated
    after running `mmpm update`

    Parameters:
        None

    Returns:
        None
    '''
    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))

    cyan_application: str = f"{mmpm.color.normal_cyan('application')}"
    cyan_package: str = f"{mmpm.color.normal_cyan('package')}"

    upgrades_available: bool = False
    upgrades = get_available_upgrades()

    if upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES]:
        for package in upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES]:
            print(mmpm.color.normal_green(package.title), f'[{cyan_package}]')
            upgrades_available = True

    if upgrades[mmpm.consts.MMPM]:
        upgrades_available = True
        print(f'{mmpm.color.normal_green(mmpm.consts.MMPM)} [{cyan_application}]')

    if upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.MAGICMIRROR]:
        upgrades_available = True
        print(f'{mmpm.color.normal_green(mmpm.consts.MAGICMIRROR)} [{cyan_application}]')

    if upgrades_available:
        print('Run `mmpm upgrade` to upgrade available packages/applications')
    else:
        print(f'No upgrades available {mmpm.consts.YELLOW_X}')


def get_available_upgrades() -> dict:
    '''
    Parses the mmpm-available-upgrades.json file, and ensures the contents are
    valid. If the contents are malformed, the file is reset.

    Parameters:
        None

    Returns:
        available_upgrades (dict): a dictionary containg the upgrades available
                                   for every MagicMirror environment encountered

    '''
    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))

    reset_file: bool = False
    add_key: bool = False

    with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'r') as available_upgrades:
        try:
            upgrades: dict = json.load(available_upgrades)
            upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES] = mmpm.utils.list_of_dict_to_list_of_magicmirror_packages(
                upgrades[MMPM_MAGICMIRROR_ROOT][mmpm.consts.PACKAGES]
            )
        except json.JSONDecodeError:
            reset_file = True
        except KeyError:
            add_key = True

    if reset_file:
        with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'w') as available_upgrades:
            upgrades = {mmpm.consts.MMPM: False, MMPM_MAGICMIRROR_ROOT: {mmpm.consts.PACKAGES: [], mmpm.consts.MAGICMIRROR: False}}
            json.dump(upgrades, available_upgrades)

    elif add_key:
        with open(mmpm.consts.MMPM_AVAILABLE_UPGRADES_FILE, 'w') as available_upgrades:
            upgrades[MMPM_MAGICMIRROR_ROOT] = {mmpm.consts.PACKAGES: [], mmpm.consts.MAGICMIRROR: False}
            json.dump(upgrades, available_upgrades)

    return upgrades


def get_installed_packages(packages: Dict[str, List[MagicMirrorPackage]]) -> Dict[str, List[MagicMirrorPackage]]:
    '''
    Scans the list <MMPM_MAGICMIRROR_ROOT>/modules directory, and compares
    against the known packages from the MagicMirror 3rd Party Wiki. Returns a
    dictionary of all found packages

    Parameters:
        packages (Dict[str, List[MagicMirrorPackage]]): Dictionary of MagicMirror packages

    Returns:
        installed_modules (Dict[str, List[MagicMirrorPackage]]): Dictionary of installed MagicMirror packages
    '''

    package_dirs: List[str] = mmpm.utils.get_existing_package_directories()

    if not package_dirs:
        mmpm.utils.env_variables_error_msg('Failed to find MagicMirror root directory.')
        return {}

    MAGICMIRROR_MODULES_DIR: str = os.path.join(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV), 'modules')

    os.chdir(MAGICMIRROR_MODULES_DIR)

    installed_packages: Dict[str, List[MagicMirrorPackage]] = {}
    packages_found: Dict[str, List[MagicMirrorPackage]] = {mmpm.consts.PACKAGES: []}

    for package_dir in package_dirs:
        if not os.path.isdir(package_dir) or not os.path.exists(os.path.join(os.getcwd(), package_dir, '.git')):
            continue

        try:
            os.chdir(os.path.join(MAGICMIRROR_MODULES_DIR, package_dir))

            error_code, remote_origin_url, stderr = mmpm.utils.run_cmd(
                ['git', 'config', '--get', 'remote.origin.url'],
                progress=False
            )

            if error_code:
                mmpm.utils.error_msg(f'Unable to communicate with git server to retrieve information about {package_dir}')
                continue

            error_code, project_name, stderr = mmpm.utils.run_cmd(
                ['basename', remote_origin_url.strip(), '.git'],
                progress=False
            )

            if error_code:
                mmpm.utils.error_msg(f'Unable to determine repository origin for {project_name}')
                continue

            packages_found[mmpm.consts.PACKAGES].append(
                MagicMirrorPackage(
                    title=project_name.strip(),
                    repository=remote_origin_url.strip(),
                    directory=os.getcwd()
                )
            )

        except Exception:
            mmpm.utils.error_msg(stderr)

        finally:
            os.chdir('..')

    for category, package_names in packages.items():
        installed_packages.setdefault(category, [])

        for package in package_names:
            for package_found in packages_found[mmpm.consts.PACKAGES]:
                if package.repository == package_found.repository:
                    package.directory = package_found.directory
                    installed_packages[category].append(package)

    return installed_packages


def add_external_package(title: str = None, author: str = None, repo: str = None, description: str = None) -> str:
    '''
    Adds an external source for user to install a module from. This may be a
    private git repo, or a specific branch of a public repo. All modules added
    in this manner will be added to the 'External Module Sources' category.
    These sources are stored in ~/.config/mmpm/mmpm-external-packages.json

    Parameters:
        title (str): External source title
        author (str): External source author
        repo (str): External source repo url
        description (str): External source description

    Returns:
        (bool): Upon success, a True result is returned
    '''
    try:
        if not title:
            title = mmpm.utils.assert_valid_input('Title: ')
        else:
            print(f'Title: {title}')

        if not author:
            author = mmpm.utils.assert_valid_input('Author: ')
        else:
            print(f'Author: {author}')

        if not repo:
            repo = mmpm.utils.assert_valid_input('Repository: ')
        else:
            print(f'Repository: {repo}')

        if not description:
            description = mmpm.utils.assert_valid_input('Description: ')
        else:
            print(f'Description: {description}')

    except KeyboardInterrupt:
        mmpm.utils.keyboard_interrupt_log()

    external_package = MagicMirrorPackage(title=title, repository=repo, author=author, description=description)

    try:
        if os.path.exists(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE) and os.stat(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE).st_size:
            config: dict = {}

            with open(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE, 'r') as mmpm_ext_srcs:
                config[mmpm.consts.EXTERNAL_PACKAGES] = mmpm.utils.list_of_dict_to_list_of_magicmirror_packages(json.load(mmpm_ext_srcs)[mmpm.consts.EXTERNAL_PACKAGES])

            with open(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE, 'w') as mmpm_ext_srcs:
                config[mmpm.consts.EXTERNAL_PACKAGES].append(external_package)
                json.dump(config, mmpm_ext_srcs, default=lambda pkg: pkg.serialize())
        else:
            # if file didn't exist previously, or it was empty, this is the first external package that's been added
            with open(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE, 'w') as mmpm_ext_srcs:
                json.dump({mmpm.consts.EXTERNAL_PACKAGES: [external_package]}, mmpm_ext_srcs, default=lambda pkg: pkg.serialize())

        print(mmpm.color.normal_green(f"\nSuccessfully added {title} to '{mmpm.consts.EXTERNAL_PACKAGES}'\n"))

    except IOError as error:
        mmpm.utils.error_msg('Failed to save external module')
        return str(error)

    return ''


def remove_external_package_source(titles: List[str] = None, assume_yes: bool = False) -> bool:
    '''
    Allows user to remove an external source from the sources saved in
    ~/.config/mmpm/mmpm-external-packages.json

    Parameters:
        titles (List[str]): External source titles

    Returns:
        success (bool): True on success, False on error
    '''

    if not os.path.exists(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE):
        mmpm.utils.fatal_msg(f'{mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE} does not appear to exist')

    elif not os.stat(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE).st_size:
        mmpm.utils.fatal_msg(f'{mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE} is empty')

    ext_packages: Dict[str, List[MagicMirrorPackage]] = {}
    marked_for_removal: List[MagicMirrorPackage] = []
    cancelled_removal: List[MagicMirrorPackage] = []

    with open(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE, 'r') as mmpm_ext_srcs:
        ext_packages[mmpm.consts.EXTERNAL_PACKAGES] = mmpm.utils.list_of_dict_to_list_of_magicmirror_packages(json.load(mmpm_ext_srcs)[mmpm.consts.EXTERNAL_PACKAGES])

    if not ext_packages[mmpm.consts.EXTERNAL_PACKAGES]:
        mmpm.utils.fatal_msg('No external packages found in database')

    for title in titles:
        for package in ext_packages[mmpm.consts.EXTERNAL_PACKAGES]:
            if package.title == title:
                prompt: str = f'Would you like to remove {mmpm.color.normal_green(title)} ({package.repository}) from the MMPM/MagicMirror local database?'
                if mmpm.utils.prompt_user(prompt, assume_yes=assume_yes):
                    marked_for_removal.append(package)
                else:
                    cancelled_removal.append(package)

    if not marked_for_removal and not cancelled_removal:
        mmpm.utils.error_msg('No external sources found matching provided query')
        return False

    for package in marked_for_removal:
        ext_packages[mmpm.consts.EXTERNAL_PACKAGES].remove(package)
        print(f'Removed {package.title} ({package.repository}) {mmpm.consts.GREEN_CHECK_MARK}')

    # if the error_msg was triggered, there's no need to even bother writing back to the file
    with open(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE, 'w') as mmpm_ext_srcs:
        json.dump(ext_packages, mmpm_ext_srcs, default=lambda pkg: pkg.serialize())

    return True


def display_magicmirror_modules_status() -> None:
    '''
    Parses the MagicMirror config file for the modules listed, and reports
    which modules are currently enabled. A module is considered disabled if the
    module explictly contains a 'disabled' flag with a 'true' value. Otherwise,
    the module is considered enabled.

    Parameters:
        None

    Returns:
        None
    '''

    client = mmpm.utils.socketio_client_factory()
    MMPM_MAGICMIRROR_URI: str = mmpm.utils.get_env(mmpm.consts.MMPM_MAGICMIRROR_URI_ENV)

    @client.on('connect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def connect(): # pylint: disable=unused-variable
        mmpm.utils.log.info('connected to MagicMirror websocket')
        client.emit('FROM_MMPM_APP_get_active_modules', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE, data=None)
        mmpm.utils.log.info('emitted request for active modules to MMPM module')


    @client.event
    def connect_error(): # pylint: disable=unused-variable
        mmpm.utils.error_msg('Failed to connect to MagicMirror websocket. Is the MMPM_MAGICMIRROR_URI environment variable set properly?')


    @client.on('disconnect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def disconnect(): # pylint: disable=unused-variable
        mmpm.utils.log.info('disconnected from MagicMirror websocket')


    @client.on('ACTIVE_MODULES', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def active_modules(data): # pylint: disable=unused-variable
        mmpm.utils.log.info('received active modules from MMPM MagicMirror module')

        if not data:
            mmpm.utils.error_msg('No data was received from the MagicMirror websocket. Is the MMPM_MAGICMIRROR_URI environment variable set properly?')

        # on rare occasions, the result is sent back twice, I suppose due to timing issues
        unique_data = [json_data for index, json_data in enumerate(data) if json_data not in data[index + 1:]]

        for module in unique_data:
            print(f"{mmpm.color.normal_green(module['name'])}\n  hidden: {'true' if module['hidden'] else 'false'}\n")

        mmpm.utils.socketio_client_disconnect(client)

    mmpm.utils.log.info(f"attempting to connect to '{mmpm.consts.MMPM_SOCKETIO_NAMESPACE}' namespace within MagicMirror websocket")

    try:
        client.connect(MMPM_MAGICMIRROR_URI, namespaces=[mmpm.consts.MMPM_SOCKETIO_NAMESPACE])
    except (OSError, BrokenPipeError) as error:
        mmpm.utils.log.warning(str(error))



def hide_magicmirror_modules(modules_to_hide: List[str]):
    '''
    Creates a connection to the websocket opened by MagicMirror, and through
    the MMPM module, the provided module names are looked up, and hidden.
    If the module is already hidden, the display doesn't change.

    Parameters:
        modules_to_hide (List[str]): the names of the modules to make visible

    Returns:
        None
    '''

    client = mmpm.utils.socketio_client_factory()
    MMPM_MAGICMIRROR_URI: str = mmpm.utils.get_env(mmpm.consts.MMPM_MAGICMIRROR_URI_ENV)

    @client.on('connect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def connect(): # pylint: disable=unused-variable
        mmpm.utils.log.info('connected to MagicMirror websocket')
        client.emit('FROM_MMPM_APP_hide_modules', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE, data=modules_to_hide)
        mmpm.utils.log.info('emitted request to hide modules to MMPM module')


    @client.event
    def connect_error(): # pylint: disable=unused-variable
        mmpm.utils.error_msg('Failed to connect to MagicMirror websocket. Is the MMPM_MAGICMIRROR_URI environment variable set properly?')


    @client.on('disconnect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def disconnect(): # pylint: disable=unused-variable
        mmpm.utils.log.info('disconnected from MagicMirror websocket')


    @client.on('MODULES_HIDDEN', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def modules_hidden(data): # pylint: disable=unused-variable
        mmpm.utils.log.info('received hidden modules from MMPM MagicMirror module')

        if not data:
            mmpm.utils.error_msg('Unable to find provided module')
        elif data['fails']:
            # on rare occasions, the result is sent back twice, I suppose due to timing issues
            fails: set = set(data['fails'])
            mmpm.utils.error_msg(f"Failed to hide {fails}. Is the name of the each module spelled correctly?")

        mmpm.utils.socketio_client_disconnect(client)

    mmpm.utils.log.info(f"attempting to connect to '{mmpm.consts.MMPM_SOCKETIO_NAMESPACE}' namespace within MagicMirror websocket")
    try:
        client.connect(MMPM_MAGICMIRROR_URI, namespaces=[mmpm.consts.MMPM_SOCKETIO_NAMESPACE])
    except (OSError, BrokenPipeError) as error:
        mmpm.utils.log.warning(str(error))

def show_magicmirror_modules(modules_to_show: List[str]) -> None:
    '''
    Creates a connection to the websocket opened by MagicMirror, and through
    the MMPM module, the provided module names are looked up, and made visible.
    If the module is already visible, the display doesn't change.

    Parameters:
        modules_to_show (List[str]): the names of the modules to make visible

    Returns:
        None
    '''

    client = mmpm.utils.socketio_client_factory()
    MMPM_MAGICMIRROR_URI: str = mmpm.utils.get_env(mmpm.consts.MMPM_MAGICMIRROR_URI_ENV)

    @client.on('connect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def connect(): # pylint: disable=unused-variable
        mmpm.utils.log.info('connected to MagicMirror websocket')
        client.emit('FROM_MMPM_APP_show_modules', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE, data=modules_to_show)
        mmpm.utils.log.info('emitted request for show modules to MMPM module')


    @client.event
    def connect_error(): # pylint: disable=unused-variable
        mmpm.utils.error_msg('Failed to connect to MagicMirror websocket. Is the MMPM_MAGICMIRROR_URI environment variable set properly?')


    @client.on('disconnect', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def disconnect(): # pylint: disable=unused-variable
        mmpm.utils.log.info('disconnected from MagicMirror websocket')


    @client.on('MODULES_SHOWN', namespace=mmpm.consts.MMPM_SOCKETIO_NAMESPACE)
    def modules_shown(data): # pylint: disable=unused-variable
        mmpm.utils.log.info('received active modules from MMPM MagicMirror module')

        if not data:
            mmpm.utils.error_msg('No data was received from the MagicMirror websocket. Is the MMPM_MAGICMIRROR_URI environment variable set?')
        elif data['fails']:
            fails: set = set(data['fails'])
            mmpm.utils.error_msg(f"Failed to show: {fails}. Is the name of the each module spelled correctly?")

        mmpm.utils.socketio_client_disconnect(client)

    mmpm.utils.log.info(f"attempting to connect to '{mmpm.consts.MMPM_SOCKETIO_NAMESPACE}' namespace within MagicMirror websocket")

    try:
        client.connect(MMPM_MAGICMIRROR_URI, namespaces=[mmpm.consts.MMPM_SOCKETIO_NAMESPACE])
    except (OSError, BrokenPipeError) as error:
        mmpm.utils.log.warning(str(error))


def get_web_interface_url() -> str:
    '''
    Parses the MMPM nginx conf file for the port number assigned to the web
    interface, and returns a string containing containing the host IP and
    assigned port.

    Parameters:
        None

    Returns:
        str: The URL of the MMPM web interface
    '''

    if not os.path.exists(mmpm.consts.MMPM_NGINX_CONF_FILE):
        mmpm.utils.fatal_msg('The MMPM NGINX configuration file does not appear to exist. Is the GUI installed?')

    # this value needs to be retrieved dynamically in case the user modifies the nginx conf
    with open(mmpm.consts.MMPM_NGINX_CONF_FILE, 'r') as conf:
        mmpm_conf = conf.read()

    try:
        from re import findall
        port: str = findall(r"listen\s?\d+", mmpm_conf)[0].split()[1]
    except IndexError:
        mmpm.utils.fatal_msg('Unable to retrieve the port number of the MMPM web interface')

    from socket import gethostname, gethostbyname
    return f'http://{gethostbyname(gethostname())}:{port}'


def stop_magicmirror() -> bool:
    '''
    Stops MagicMirror using pm2, if found, otherwise the associated
    processes are killed

    Parameters:
       None

    Returns:
        None
    '''

    process: str = ''
    command: List[str] = []

    MMPM_MAGICMIRROR_PM2_PROCESS_NAME: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_PM2_PROCESS_NAME_ENV)
    MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE_ENV)

    if shutil.which('pm2') and MMPM_MAGICMIRROR_PM2_PROCESS_NAME:
        command = ['pm2', 'stop', MMPM_MAGICMIRROR_PM2_PROCESS_NAME]
        process = 'pm2'

    elif shutil.which('docker-compose') and MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE:
        command = ['docker-compose', '-f', MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE, 'stop']
        process = 'docker-compose'

    if command and process:
        mmpm.utils.plain_print(f"{mmpm.consts.GREEN_PLUS} stopping MagicMirror using {command[0]} ")
        mmpm.utils.log.info(f"Using '{process}' to stop MagicMirror")
        # pm2 and docker-compose cause the output to flip
        error_code, stderr, _ = mmpm.utils.run_cmd(command, progress=False)

        if error_code:
            print(mmpm.consts.RED_X)
            mmpm.utils.env_variables_error_msg(stderr.strip())
            return False

        mmpm.utils.log.info(f"stopped MagicMirror using '{process}'")
        print(mmpm.consts.GREEN_CHECK_MARK)
        return True

    mmpm.utils.kill_magicmirror_processes()
    return True


def start_magicmirror() -> bool:
    '''
    Launches MagicMirror using pm2, if found, otherwise a 'npm start' is run as
    a background process

    Parameters:
       None

    Returns:
        None
    '''
    mmpm.utils.log.info('Starting MagicMirror')

    process: str = ''
    command: List[str] = []

    MMPM_MAGICMIRROR_PM2_PROCESS_NAME: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_PM2_PROCESS_NAME_ENV)
    MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE_ENV)

    if shutil.which('pm2') and MMPM_MAGICMIRROR_PM2_PROCESS_NAME:
        command = ['pm2', 'start', MMPM_MAGICMIRROR_PM2_PROCESS_NAME]
        process = 'pm2'

    elif shutil.which('docker-compose') and MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE:
        command = ['docker-compose', '-f', MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE, 'up', '-d']
        process = 'docker-compose'

    if command and process:
        mmpm.utils.plain_print(f"{mmpm.consts.GREEN_PLUS} starting MagicMirror using {command[0]} ")
        mmpm.utils.log.info(f"Using '{process}' to start MagicMirror")
        error_code, stderr, _ = mmpm.utils.run_cmd(command, progress=False)

        if error_code:
            print(mmpm.consts.RED_X)
            mmpm.utils.env_variables_error_msg(stderr.strip())
            return False

        mmpm.utils.log.info(f"started MagicMirror using '{process}'")
        print(mmpm.consts.GREEN_CHECK_MARK)
        return True

    MMPM_MAGICMIRROR_ROOT: str = os.path.normpath(get_env(mmpm.consts.MMPM_MAGICMIRROR_ROOT_ENV))

    os.chdir(MMPM_MAGICMIRROR_ROOT)
    mmpm.utils.log.info("Running 'npm start' in the background")

    mmpm.utils.plain_print(f'{mmpm.consts.GREEN_PLUS} npm start ')
    os.system('npm start &')
    print(mmpm.consts.GREEN_CHECK_MARK)
    mmpm.utils.log.info("Using 'npm start' to start MagicMirror. Stdout/stderr capturing not possible in this case")
    return True


def restart_magicmirror() -> bool:
    '''
    Restarts MagicMirror using pm2, if found, otherwise the associated
    processes are killed and 'npm start' is re-run a background process

    Parameters:
       None

    Returns:
        None
    '''

    process: str = ''
    command: List[str] = []

    MMPM_MAGICMIRROR_PM2_PROCESS_NAME: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_PM2_PROCESS_NAME_ENV)
    MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE: str = get_env(mmpm.consts.MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE_ENV)

    if shutil.which('pm2') and MMPM_MAGICMIRROR_PM2_PROCESS_NAME:
        command = ['pm2', 'restart', MMPM_MAGICMIRROR_PM2_PROCESS_NAME]
        process = 'pm2'

    elif shutil.which('docker-compose') and MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE:
        command = ['docker-compose', '-f', MMPM_MAGICMIRROR_DOCKER_COMPOSE_FILE, 'restart']
        process = 'docker-compose'

    if command and process:
        mmpm.utils.plain_print(f"{mmpm.consts.GREEN_PLUS} restarting MagicMirror using {command[0]} ")
        mmpm.utils.log.info(f"Using '{process}' to restart MagicMirror")
        # pm2 and docker-compose cause the output to flip
        error_code, stderr, _ = mmpm.utils.run_cmd(command, progress=False)

        if error_code:
            print(mmpm.consts.RED_X)
            mmpm.utils.env_variables_error_msg(stderr.strip())
            return False

        mmpm.utils.log.info(f"restarted MagicMirror using '{process}'")
        print(mmpm.consts.GREEN_CHECK_MARK)
        return True

    if not stop_magicmirror():
        mmpm.utils.log.error('Failed to stop MagicMirror using npm commands')
        return False

    if not start_magicmirror():
        mmpm.utils.log.error('Failed to start MagicMirror using npm commands')
        return False

    mmpm.utils.log.info('Restarted MagicMirror using npm commands')
    return True


def display_log_files(cli_logs: bool = False, gui_logs: bool = False, tail: bool = False) -> None:
    '''
    Displays contents of log files to stdout. If the --tail option is supplied,
    log contents will be displayed in real-time

    Parameters:
       cli_logs (bool): if True, the CLI log files will be displayed
       gui_logs (bool): if True, the Gunicorn log files for the web interface will be displayed
       tail (bool): if True, the contents will be displayed in real time

    Returns:
        None
    '''
    logs: List[str] = []

    if cli_logs:
        if os.path.exists(mmpm.consts.MMPM_CLI_LOG_FILE):
            logs.append(mmpm.consts.MMPM_CLI_LOG_FILE)
        else:
            mmpm.utils.error_msg('MMPM log file not found')

    if gui_logs:
        if os.path.exists(mmpm.consts.MMPM_GUNICORN_ACCESS_LOG_FILE):
            logs.append(mmpm.consts.MMPM_GUNICORN_ACCESS_LOG_FILE)
        else:
            mmpm.utils.error_msg('Gunicorn access log file not found')
        if os.path.exists(mmpm.consts.MMPM_GUNICORN_ERROR_LOG_FILE):
            logs.append(mmpm.consts.MMPM_GUNICORN_ERROR_LOG_FILE)
        else:
            mmpm.utils.error_msg('Gunicorn error log file not found')

    if logs:
        os.system(f"{'tail -F' if tail else 'cat'} {' '.join(logs)}")


def display_mmpm_env_vars() -> None:
    '''
    Displays the environment variables associated with MMPM, as well as their
    current value. A user may modify these values by setting them in their
    shell configuration file

    Parameters:
        detailed (bool): if True, comments displaying the usage of the
                         environment variables are displayed

    Returns:
        None
    '''

    mmpm.utils.log.info('User listing environment variables, set with the following values')

    from pygments import highlight, formatters
    from pygments.lexers.data import JsonLexer

    with open(mmpm.consts.MMPM_ENV_FILE, 'r') as env:
        print(highlight(json.dumps(json.load(env), indent=2), JsonLexer(), formatters.TerminalFormatter()))

    print('Run `mmpm open --env` to edit the variable values')


def install_autocompletion(assume_yes: bool = False) -> None:
    '''
    Adds autocompletion configuration to a user's shell configuration file.
    Detects configuration files for bash, zsh, fish, and tcsh

    Parameters:
        assume_yes (bool): if True, assume yes for user response, and do not display prompt

    Returns:
        None
    '''

    if not mmpm.utils.prompt_user('Are you sure you want to install the autocompletion feature for the MMPM CLI?', assume_yes=assume_yes):
        mmpm.utils.log.info('User cancelled installation of autocompletion for MMPM CLI')
        return

    mmpm.utils.log.info('user attempting to install MMPM autocompletion')
    shell: str = os.environ['SHELL']

    mmpm.utils.log.info(f'detected user shell to be {shell}')

    autocomplete_url: str = 'https://github.com/kislyuk/argcomplete#activating-global-completion'
    error_message: str = f'Please see {autocomplete_url} for help installing autocompletion'

    complete_message = lambda config: f'Autocompletion installed. Please source {config} for the changes to take effect'
    failed_match_message = lambda shell, configs: f'Unable to locate {shell} configuration file (looked for {configs}). {error_message}'

    def __match_shell_config__(configs: List[str]) -> str:
        mmpm.utils.log.info(f'searching for one of the following shell configuration files {configs}')
        for config in configs:
            config = os.path.join(mmpm.consts.HOME_DIR, config)
            if os.path.exists(config):
                mmpm.utils.log.info(f'found {config} shell configuration file for {shell}')
                return config
        return ''

    def __echo_and_eval__(command: str) -> None:
        mmpm.utils.log.info(f'executing {command} to install autocompletion')
        print(f'{mmpm.consts.GREEN_PLUS} {command}')
        os.system(command)

    if 'bash' in shell:
        files = ['.bashrc', '.bash_profile', '.bash_login', '.profile']
        config = __match_shell_config__(files)

        if not config:
            mmpm.utils.fatal_msg(failed_match_message('bash', files))

        __echo_and_eval__(f'echo \'eval "$(register-python-argcomplete mmpm)"\' >> {config}')

        print(complete_message(config))

    elif 'zsh' in shell:
        files = ['.zshrc', '.zprofile', '.zshenv', '.zlogin', '.profile']
        config = __match_shell_config__(files)

        if not config:
            mmpm.utils.fatal_msg(failed_match_message('zsh', files))

        __echo_and_eval__(f"echo 'autoload -U bashcompinit' >> {config}")
        __echo_and_eval__(f"echo 'bashcompinit' >> {config}")
        __echo_and_eval__(f'echo \'eval "$(register-python-argcomplete mmpm)"\' >> {config}')

        print(complete_message(config))

    elif 'tcsh' in shell:
        files = ['.tcshrc', '.cshrc', '.login']
        config = __match_shell_config__(files)

        if not config:
            mmpm.utils.fatal_msg(failed_match_message('tcsh', files))

        __echo_and_eval__(f"echo 'eval `register-python-argcomplete --shell tcsh mmpm`' >> {config}")

        print(complete_message(config))

    elif 'fish' in shell:
        files = ['.config/fish/config.fish']
        config = __match_shell_config__(files)

        if not config:
            mmpm.utils.fatal_msg(failed_match_message('fish', files))

        __echo_and_eval__(f"register-python-argcomplete --shell fish mmpm >> {config}")

        print(complete_message(config))

    else:
        mmpm.utils.fatal_msg(f'Unable install autocompletion for ({shell}). Please see {autocomplete_url} for help installing autocomplete')


def rotate_raspberrypi_screen(degrees: int) -> str:
    '''
    Rotates screen of RaspberryPi 3 and RaspberryPi 4 to the setting supplied
    by the user

    Parameters:
        degrees (int): desired setting in degrees

    Returns:
        error (str): empty if on success, error message on failure
    '''

    import re

    config: str = '/boot/config.txt'

    rotation_map: Dict[int, int] = {
        0: 0,
        90: 3,
        180: 2,
        270: 1
    }

    if os.path.exists('/proc/device-tree/model'):
        with open('/proc/device-tree/model', 'r') as model_info:
            rpi_model = model_info.read()

        if 'Raspberry Pi 3' in rpi_model:
            desired_setting: str = f'display_rotate={rotation_map[degrees]}'
            pattern: str = r'display_rotate=\d'

            # this really should exist anyway
            if not os.path.exists(config):
                os.system(f'sudo touch {config}')

            with open(config, 'r+') as cfg:
                contents: str = cfg.read()
                setting: List[str] = re.findall(pattern, contents)

                if not setting:
                    # this file should not be empty, but just in case
                    contents += f'\n{desired_setting}\n'
                else:
                    contents = re.sub(pattern, desired_setting, contents, count=1)

                cfg.seek(0)
                cfg.write(contents)

        elif 'Raspberry Pi 4' in rpi_model:
            mmpm.utils.warning_msg('Sorry, this has not been implemented yet')

    else:
        message: str = 'Display rotation has not been implemented for this type device. Only Raspberry Pi 3 is supported for the moment'
        mmpm.utils.error_msg(message)
        return message

    print('Please restart your RaspberryPi for the changes to take effect')
    return ''


def migrate() -> None:
    '''
    Migrates legacy External Module Sources to External Packages. The legacy
    file name of ~/.config/mmpm/mmpm-external-sources.json is renamed to
    ~/.config/mmpm/mmpm-external-packages.json. The key inside the dictionary
    is also renamed from 'External Module Sources' to 'External Packages'

    Parameters:
        None

    Returns:
        None
    '''
    import pathlib

    legacy_ext_src_file: str = os.path.join(mmpm.consts.MMPM_CONFIG_DIR, 'mmpm-external-sources.json')
    legacy_key: str = 'External Module Sources'
    data: dict = {}

    if os.path.exists(legacy_ext_src_file):
        with open(legacy_ext_src_file, 'r') as legacy_file:
            mmpm.utils.log.info('Found existing legacy external modules sources file')
            try:
                data = json.load(legacy_file)

                if legacy_key in data:
                    mmpm.utils.log.info(f'Updating {legacy_key} in external modules dictionary to {mmpm.consts.EXTERNAL_PACKAGES}')
                    data[mmpm.consts.EXTERNAL_PACKAGES] = data[legacy_key]
                    data.pop(legacy_key)

                else:
                    mmpm.utils.log.info('No data found in the legacy key, resetting with empty list')
                    data[mmpm.consts.EXTERNAL_PACKAGES] = []

            except json.JSONDecodeError:
                mmpm.utils.fatal_msg(f'{legacy_ext_src_file} may be corrupted. Please examine the file')

        mmpm.utils.log.info(f'Renaming external packages file from {legacy_ext_src_file} to {mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE}')
        pathlib.Path(legacy_ext_src_file).rename(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE)

        with open(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE, 'w') as ext_pkgs:
            mmpm.utils.log.info('Saving updated external packages data')
            json.dump(data, ext_pkgs)

    else:
        mmpm.utils.log.info(f'{legacy_ext_src_file} does not exist, nothing to migrate')

    mmpm.utils.log.info('Completed migration of legacy External Module Sources migrated to External Packages')
    print('Migration complete!')


def dump_database() -> None:
    '''
    Prints contents of database to stdout

    Parameters:
        None

    Returns:
        None
    '''
    contents: dict = {}

    with open(mmpm.consts.MAGICMIRROR_3RD_PARTY_PACKAGES_DB_FILE, 'r') as db:
        try:
            contents.update(json.load(db))
        except json.JSONDecodeError:
            pass

    if os.stat(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE).st_size:
        with open(mmpm.consts.MMPM_EXTERNAL_PACKAGES_FILE, 'r') as db:
            try:
                contents.update(json.load(db))
            except json.JSONDecodeError:
                pass

    from pygments import highlight, formatters
    from pygments.lexers.data import JsonLexer

    print(highlight(json.dumps(contents, indent=2), JsonLexer(), formatters.TerminalFormatter()))