from datetime import datetime
import html
import json
import os
import re
import sys
import subprocess
import tarfile
import time
import urllib.request
from urllib.parse import urljoin

# -------- constants

URL__LATEST_INDEX = "https://cloud.r-project.org/web/packages/available_packages_by_name.html"
"""available mirrors can be checked here: https://cran.r-project.org/mirrors.html"""

URL__ARCHIVE_INDEX = "https://cran.r-project.org/src/contrib/Archive/"

PATH_STORAGE = "./r_packages"
PATH_CACHE = "./cache"
"""to store HTML and index files, so that if you use the script in the same day, it can be reused instead of fetching again"""

FETCH_MAX_RETRY = 5
FETCH_BETWEEN_RETRY = 3 # in seconds

SEPERATOR_VERSION = "@"

RE = {
  "R_VERSION": r'^(\d+(?:[.]\d+)*)$', # regexp to test R version string; pass: like `4`, `4.2`, `4.2.1`; failed: like `.2`, `4.2.`, `4.2.1.5`, `4.2.1a`
  "LATEST_INDEX__ALL_TD": r'<td.*?<a(.*?)</td>',
  "LATEST_INDEX__PACKAGE_NAME": r'<span.*?>(.*?)</span>',
  "LATEST_INDEX__URL": r'href.*?=.*?"(.*?)"',
  "ARCHIVE_INDEX__ALL_TR": r'<tr.*?<td.*?<a(.*?)</a>.*?</tr>',
  "ARCHIVE_INDEX__URL": r'href.*?=.*?"(.*?)"',
  "ARCHIVE_INDEX__PACKAGE_NAME": r'>(.*?)[/]?$',
  "LATEST_META__TABLE": r'<table(.*?)</table>',
  "LATEST_META__VERSION": r'<tr.*?<td.*?version.*?</td>.*?<td>(.*?)</td>.*?</tr>',
  "LATEST_META__DATE": r'<tr.*?<td.*?published.*?</td>.*?<td>(.*?)</td>.*?</tr>',
  "LATEST_META__DEPENDENCIES": r'<tr.*?<td.*?depend.*?</td>.*?<td>(.*?)</td>.*?</tr>',
  "LATEST_META__DEPENDENCY_R": r'R.*?(=|<|>|>=|<=|≥|≤).*?(\d+(?:[.]\d+)*)',
  "LATEST_META__SPAN_ITEM": r'<span.*?>(.*?)</span>',
  "LATEST_META__IMPORTS": r'<tr.*?<td.*?import.*?</td>.*?<td>(.*?)</td>.*?</tr>',
  "LATEST_META__LINKS": r'<tr.*?<td.*?linking.*?</td>.*?<td>(.*?)</td>.*?</tr>',
  "ARCHIVE__VERSION_INDEX__ALL_TR": r'<tr.*?<a.*?href.*?=.*?"([^"]*?[.]tar[.]gz)".*?<td.*?>(.*?)</td>.*?</tr>',
  "ARCHIVE__VERSION_INDEX__VERSION": r'.*?_(.*?).tar.gz',
  "DESCRIPTION__DEPENDENCIES": r'depend.*?:(.*?)\n',
  "DESCRIPTION__IMPORTS": r'import.*?:(.*?)\n',
  "DESCRIPTION__LINKS": r'link.*?:(.*?)\n'
}

def initialize__RE():
  # iterate RE, compile them
  for key, value in RE.items():
    RE[key] = re.compile(value, re.IGNORECASE | re.DOTALL)
  success("ready")

# -------- variables

formatted_date__when_start = None

if__using_cache = None

dict__latest_index = {}
dict__archive_index = {}

r_start = "R"
str_R_version = None

dict__dependencies_tree = {}
list__error_packages = []
list__tmp_dependencies_info_items = []

# -------- console output

ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_RESET = "\033[0m"

def success(content):
  print(f"{ANSI_GREEN}✔️  {content}{ANSI_RESET}")

def warning(content):
  print(f"{ANSI_YELLOW}❗ {content}{ANSI_RESET}")

def error(content):
  print(f"{ANSI_RED}❗❗❗  {content}{ANSI_RESET}")

# -------- utils

def get__fotmatted_date():
  return time.strftime("%Y%m%d", time.localtime())

def ask__user_confirm(prompt, str__default_input="y"):
  str__default = "(Y/n)"
  if str__default_input == "n":
    str__default = "(y/N)"

  print("\n--------\n")
  str__confirm = input(f"❗ please confirm opration:\n  {prompt} {str__default}: ").strip().lower()
  print("\n")
  
  if str__confirm == "":
    str__confirm = str__default_input.strip().lower()

  if (str__confirm == "y") or (str__confirm == "yes"):
    return True
  elif (str__confirm == "n") or (str__confirm == "no"):
    return False
  else:
    error(f"unrecognized answer: expected 'y' or 'n', but got '{str__confirm}', exit")
    exit(1)
    
def save__file(path__file, content):
  print(f"try save file to:\n  {path__file}")
  try:
    with open(path__file, "w") as f:
      f.write(content)
    success("file saved")
  except Exception as e:
    error(f"failed to save file to {path__file}:\n  {e}")
    exit(1)

def fetch__HTML__from__URL(str__URL):
  retry_times = FETCH_MAX_RETRY
  def try_fetch():
    nonlocal retry_times
    try:
      with urllib.request.urlopen(str__URL) as response:
        str__HTML = html.unescape(response.read().decode("utf-8"))
        return str__HTML
    except Exception as e:
      warning(f"failed to fetch HTML from {str__URL}:\n  {e}\n  {retry_times} retries left in {FETCH_BETWEEN_RETRY} seconds...")
      retry_times -= 1
      if retry_times > 0:
        time.sleep(FETCH_BETWEEN_RETRY)
        return try_fetch()
      else:
        error(f"failed to fetch HTML from {str__URL} after {FETCH_MAX_RETRY} times retry, exit")
        exit(1)
  return try_fetch()

def download__file_from__URL(str__URL, path__file):
  print(f"try download file from:\n  {str__URL}")
  try:
    urllib.request.urlretrieve(str__URL, path__file)
    success("file downloaded")
  except Exception as e:
    error(f"download failed:\n  {e}")
    exit(1)

# -------- logic

# def detect_R_start():
#   global r_start
#   print("detect R's start location by R_HOME...")
#   r_home = os.getenv("R_HOME")
#   if r_home:
#     r_start = f"{os.path.join(r_home, 'bin', 'R')}"
#     success(f"R start location loaded:\n  {r_home}")
#   else:
#     warning("R_HOME not found, better to check it")

# def get_current_R_version():
#   global str__R_version
#   try:
#     print("get R version...")
#     formatted_date = subprocess.run(f"{r_start} --version", shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()
#     if formatted_date:
#       str__R_version = formatted_date
#     if str__R_version:
#       success(f"R version:\n  {str__R_version}")
#     else:
#       error("R version not found, exit")
#       exit(1)
#   except Exception as e:
#     error(e)

# def initialize():
#   detect_R_start()
#   get_current_R_version()

def if__date_unsure__not_later_than__date_target(str__date_unsure, str__date_target):
  try:
    date_unsure = datetime.strptime(str__date_unsure, "%Y-%m-%d")
    date_target = datetime.strptime(str__date_target, "%Y-%m-%d")
    if date_unsure > date_target:
      return False
    else:
      return True
  except Exception as e:
    error(f"date comparison failed:\n  {e}")
    return False

def try_get__HTML__then_parse(file_name, str__URL, func__parse_from_HTML):
  global if__using_cache

  path__file = os.path.join(PATH_CACHE, f"{formatted_date__when_start}_{file_name}.html")

  str__HTML = None

  if os.path.exists(path__file):
    if if__using_cache == None: # only ask once if using cache
      if__using_cache = not ask__user_confirm("very recent cache found, force fetch new?", "n")

    if if__using_cache:
      with open(path__file, "r") as f:
        str__HTML = f.read()
      success(f"cache loaded:\n  {path__file}")

  # fetch HTML
  if str__HTML == None:
    str__HTML = fetch__HTML__from__URL(str__URL)
    save__file(path__file, str__HTML)

  # parse HTML
  dict__content = func__parse_from_HTML(str__HTML)

  return dict__content
    
def try_get__dict(file_name, str__URL, func__parse_from_HTML):
  global if__using_cache

  path__file = os.path.join(PATH_CACHE, f"{formatted_date__when_start}_{file_name}.json")

  # if cache exists and loaded
  if os.path.exists(path__file):
    if if__using_cache == None: # only ask once if using cache
      if__using_cache = not ask__user_confirm("very recent cache found, force fetch new?", "n")

    if if__using_cache:
      with open(path__file, "r") as f:
        dict__content = json.load(f)
      success(f"cache loaded:\n  {path__file}")
      return dict__content

  # else get HTML and parse
  dict__content = try_get__HTML__then_parse(file_name, str__URL, func__parse_from_HTML)

  save__file(path__file, json.dumps(dict__content, ensure_ascii=False, indent=2))

  return dict__content

def try_get__dict__from__downloaded_file(file_name, str__URL):
  global if__using_cache

  path__json = os.path.join(PATH_CACHE, f"{formatted_date__when_start}_{file_name}.json")

  path__file = os.path.join(PATH_STORAGE, f"{file_name}.tar.gz")

  # if cache exists and loaded
  if os.path.exists(path__json):
    if if__using_cache == None: # only ask once if using cache
      if__using_cache = not ask__user_confirm("very recent cache found, force fetch new?", "n")

    if if__using_cache:
      with open(path__json, "r") as f:
        dict__content = json.load(f)
      success(f"cache loaded:\n  {path__json}")
      return dict__content

  # else download file and parse
  if not os.path.exists(path__file):
    download__file_from__URL(str__URL, path__file)

  if os.path.exists(path__file):
    try:
      with tarfile.open(path__file, "r:gz") as tar:
        members = tar.getmembers()

        if__DESCRIPTION_exists = any("DESCRIPTION" == member.name for member in members)

        if if__DESCRIPTION_exists == False:
          path__DESCRIPTION = os.path.join(tar.getmembers()[0].name, "DESCRIPTION")
        else:
          path__DESCRIPTION = "DESCRIPTION"

        with tar.extractfile(path__DESCRIPTION) as f:
          str__content = f.read().decode("utf-8")
      
      success(f"R package DESCRIPTION found:\n  {path__file}")
    except Exception as e:
      error(f"failed to extract DESCRIPTION from {path__file}:\n  {e}")
      return {}

    list__dependencies_raw = RE["DESCRIPTION__DEPENDENCIES"].findall(str__content)
    list__imports_raw = RE["DESCRIPTION__IMPORTS"].findall(str__content)
    list__links_raw = RE["DESCRIPTION__LINKS"].findall(str__content)

    list__dependencies = []
    list__imports = []
    list__links = []

    if len(list__dependencies_raw) > 0:
      list__dependencies = list__dependencies_raw[0].split(",")
    if len(list__imports_raw) > 0:
      list__imports = list__imports_raw[0].split(",")
    if len(list__links_raw) > 0:
        list__links = list__links_raw[0].split(",")

    dict__content = {
      "version": None,
      "date": None,
      "limitation_of_R_version": None,
      "dependencies": [],
      "imports": [],
      "links": []
    }

    for str__dependency in list__dependencies:
      str__dependency = str__dependency.strip()

      dependency_R_version = RE["LATEST_META__DEPENDENCY_R"].findall(str__dependency)
      if len(dependency_R_version) > 0:
        version_R = dependency_R_version[0]
        # print(f"dependency R version detected: {version_R}")
        dict__content["limitation_of_R_version"] = version_R
        continue

      dict__content["dependencies"].append(str__dependency)
    for str__import in list__imports:
      str__import = str__import.strip()
      dict__content["imports"].append(str__import)
    for str__link in list__links:
      str__link = str__link.strip()
      dict__content["links"].append(str__link)

    success(f"cache loaded:\n  {path__json}")

    save__file(path__json, json.dumps(dict__content, ensure_ascii=False, indent=2))

    return dict__content
  else:
    error(f"seems R package download failed: {path__file}")
    exit(1)

def parse__latest_package_metadata(str__HTML):
  print("parse latest package metadata...")
  dict__metadata = {}

  table__info = RE["LATEST_META__TABLE"].findall(str__HTML)[0]
  str__version = RE["LATEST_META__VERSION"].findall(table__info)[0]
  str__date = RE["LATEST_META__DATE"].findall(table__info)[0]

  limitation_of_R_version = None

  list__dependencies = []
  list__dependencies__raw = RE["LATEST_META__DEPENDENCIES"].findall(table__info)

  if len(list__dependencies__raw) > 0:
    list__tmp_dependencies = list__dependencies__raw[0].split(",")
    for tmp_dependency in list__tmp_dependencies:
      tmp_dependency = tmp_dependency.strip()
      # print(tmp_dependency)

      # check if tmp_denpendency matched RE["LATEST_META__DEPENDENCY_R"]
      dependency_R_version = RE["LATEST_META__DEPENDENCY_R"].findall(tmp_dependency)
      if len(dependency_R_version) > 0:
        version_R = dependency_R_version[0]
        # print(f"dependency R version detected: {version_R}")
        limitation_of_R_version = version_R
        continue
      
      item = RE["LATEST_META__SPAN_ITEM"].findall(tmp_dependency)

      if len(item) > 0:
        list__dependencies.append(item[0])

  list__imports = []
  list__imports__raw = RE["LATEST_META__IMPORTS"].findall(table__info)
  if len(list__imports__raw) > 0:
    list__tmp_imports = list__imports__raw[0].split(",")
    for tmp_import in list__tmp_imports:
      tmp_import = tmp_import.strip()
      # print(tmp_import)
      item = RE["LATEST_META__SPAN_ITEM"].findall(tmp_import)

      if len(item) > 0:
        list__imports.append(item[0])

  list__links = []
  list__links__raw = RE["LATEST_META__LINKS"].findall(table__info)
  if len(list__links__raw) > 0:
    list__tmp_links = list__links__raw[0].split(",")
    for tmp_link in list__tmp_links:
      tmp_link = tmp_link.strip()
      # print(tmp_link)

      item = RE["LATEST_META__SPAN_ITEM"].findall(tmp_link)

      if len(item) > 0:
        list__links.append(item[0])

  dict__metadata = {
    "version": str__version,
    "date": str__date,
    "limitation_of_R_version": limitation_of_R_version,
    "dependencies": list__dependencies,
    "imports": list__imports,
    "links": list__links
  }

  success(f"package metadata parsed:")
  # print key, value in dict__metadata joined by newline
  print("\n".join([f"  {key}: {value}" for key, value in dict__metadata.items()]))

  return dict__metadata

def parse__latest_index(str__HTML):
  print("parse latest index...")
  dict__latest_index = {}
  list__td_items = RE["LATEST_INDEX__ALL_TD"].findall(str__HTML)
  for td_item in list__td_items:
    package_name = RE["LATEST_INDEX__PACKAGE_NAME"].findall(td_item)
    relative_URL = RE["LATEST_INDEX__URL"].findall(td_item)
    if package_name and relative_URL:
      dict__latest_index[package_name[0]] = relative_URL[0]
  
  length__td_items = len(list__td_items)
  length__latest_index = len(dict__latest_index)

  if length__td_items == length__latest_index:
    success(f"all {length__latest_index} packages parsed")
  else:
    warning(f"{length__latest_index} packages parsed, but {length__td_items - length__latest_index} packages unrecognized")

  return dict__latest_index

def parse__archive_index(str__HTML):
  print("parse archive index...")
  dict__archive_index = {}
  list__tr_items = RE["ARCHIVE_INDEX__ALL_TR"].findall(str__HTML)
  for tr_item in list__tr_items:
    if len(tr_item) == 0:
      warning("empty tr_item found")
      continue
    relative_URL = RE["ARCHIVE_INDEX__URL"].findall(tr_item)
    package_name = RE["ARCHIVE_INDEX__PACKAGE_NAME"].findall(tr_item)
    
    if relative_URL and package_name:
      dict__archive_index[package_name[0]] = relative_URL[0]
  
  length__tr_items = len(list__tr_items)
  length_archive_index = len(dict__archive_index)
  
  if length__tr_items == length_archive_index:
    success(f"all {length_archive_index} packages parsed")
  else:
    warning(f"{length_archive_index} packages parsed, but {length__tr_items - length_archive_index} packages unrecognized")
  
  return dict__archive_index

def parse__archive_package_version(str__HTML):
  print("parse archive package version...")
  dict__archive_package_version = {}
  list__tr_items = RE["ARCHIVE__VERSION_INDEX__ALL_TR"].findall(str__HTML)
  for tr_item in list__tr_items:
    # print(tr_item)
    
    if len(tr_item) == 0:
      warning("empty tr_item found")
      continue

    str__relative_URL = tr_item[0]
    str_date = tr_item[1].strip().split(" ")[0]
    str__version = RE["ARCHIVE__VERSION_INDEX__VERSION"].findall(str__relative_URL)[0]

    dict__archive_package_version[str__version] = {
      "date": str_date,
      "relative_URL": str__relative_URL
    }
    # print(f"{str_date}: {str__version}")

  return dict__archive_package_version

def convert__check_status__to__str(status):
  if status:
    return "passed"
  else:
    return "failed"

def try_find__package__from__archive_index(package_name, str__version_target=None, str__date_before=None):
  global dict__archive_index

  print(f"try find '{package_name}' from archive index...")

  if len(dict__archive_index) == 0:
    print("\ntry get archive index...")
    dict__archive_index = try_get__dict("archive_index", URL__ARCHIVE_INDEX, parse__archive_index)

  if package_name in dict__archive_index:
    print("\n")
    success(f"package {package_name} found in archive index")

    print("\ntry get archive package version index...")
    dict__archive__version_index = try_get__dict(f"{package_name}_archive_version_index", urljoin(URL__ARCHIVE_INDEX, dict__archive_index[package_name]), parse__archive_package_version)

    # print(dict__archive__version_index)

    str__version_to_download = None

    if str__version_target != None:
      if str__version_target in dict__archive__version_index:
        success(f"version {str__version_target} found in archive index")
        str__version_to_download = str__version_target
      else:
        warning(f"version {str__version_target} not found in archive index")
        return {}

    if str__date_before != None:
      date__before = datetime.strptime(str__date_before, "%Y-%m-%d")
      date__recent = None
      str__recent_version = None
      for str__version, dict__info in dict__archive__version_index.items():
        str__date_tmp = dict__info["date"]
        date__tmp = datetime.strptime(str__date_tmp, "%Y-%m-%d")
        if date__tmp < date__before:
          if (date__recent == None) or (date__tmp > date__recent):
            date__recent = date__tmp
            str__recent_version = str__version

      if date__recent != None:
        success(f"recent version found: {str__recent_version} at {date__recent.strftime('%Y-%m-%d')} before {str__date_before}")
        str__version_to_download = str__recent_version
      else:
        warning(f"no recent version found before {str__date_before}")
        return {}

    str__version_URL = dict__archive__version_index[str__version_to_download]["relative_URL"]

    # print(f"debug package name: {package_name}")
    # print(f"debug version URL: {str__version_URL}")

    URL__file_to_download = urljoin(URL__ARCHIVE_INDEX, f"{package_name}/")

    # print(f"debug URL__file_to_download: {URL__file_to_download}")

    URL__file_to_download = urljoin(URL__file_to_download, str__version_URL)

    # print(f"debug URL__file_to_download: {URL__file_to_download}")

    dict__archive__metadata = try_get__dict__from__downloaded_file(f"{package_name}_v_{str__version_to_download}", URL__file_to_download)

    dict__archive__metadata["version"] = str__version_to_download
    dict__archive__metadata["date"] = dict__archive__version_index[str__version_to_download]["date"]

    print(f"debug dict__archive__metadata: {dict__archive__metadata}")

    return dict__archive__metadata
  else:
    warning(f"package '{package_name}' not found in archive index")
    return {}

def try_find__package__from__latest_index(package_name, str__version_target=None, str__date_before=None):
  global dict__latest_index

  print(f"try find '{package_name}' from latest index...")

  if len(dict__latest_index) == 0:
    print("\ntry get latest index...")
    dict__latest_index = try_get__dict("latest_index", URL__LATEST_INDEX, parse__latest_index)

  if package_name in dict__latest_index:
    print("\n")
    success(f"package {package_name} found in latest index")

    dict__latest__metadata = try_get__dict(f"{package_name}_latest_metadata", urljoin(URL__LATEST_INDEX, dict__latest_index[package_name]), parse__latest_package_metadata)

    # print(dict__latest__metadata)

    # check version and date

    if__version_check__passed = False
    if__date_check__passed = False

    if str__version_target == None:
      if__version_check__passed = True
    elif dict__latest__metadata["version"] == str__version_target:
      if__version_check__passed = True
    
    if str__date_before == None:
      if__date_check__passed = True
    elif if__date_unsure__not_later_than__date_target(dict__latest__metadata["date"], str__date_before):
      if__date_check__passed = True

    if if__version_check__passed and if__date_check__passed:
      return {
        "package_name": package_name,
        "version": dict__latest__metadata["version"],
        "date": dict__latest__metadata["date"], 
        "dependencies": dict__latest__metadata["dependencies"] + dict__latest__metadata["imports"] + dict__latest__metadata["links"]
      }
    else:
      warning(f"latest package '{package_name}' check failed:\n  version: {convert__check_status__to__str(if__version_check__passed)}\n  date: {convert__check_status__to__str(if__date_check__passed)}")
      return {}

  else: # package not found in latest index
    return {}

def split__package_name__and__version(str_package_name_and_version):
  package_name, str__version_target = str_package_name_and_version.split(SEPERATOR_VERSION)
  return package_name, str__version_target

def find__package__and__parse__dpendencies(package_name, str__version_target=None, str__date_before=None, dict__parent=None):

  print(f"\nfind package: {package_name}\n  version limit: {str__version_target}\n  before date: {str__date_before}")

  dict__result = try_find__package__from__latest_index(
    package_name, 
    str__version_target, 
    str__date_before
  )

  if len(dict__result) == 0:
    dict__result = try_find__package__from__archive_index(
      package_name, 
      str__version_target, 
      str__date_before
    )

  if len(dict__result) > 0:
    version = dict__result["version"]
    date = dict__result["date"]
    dependencies = dict__result["dependencies"]
    if "imports" in dict__result:
      dependencies += dict__result["imports"]
    if "links" in dict__result:
      dependencies += dict__result["links"]

    if "dependencies" not in dict__parent: # global dict__dependencies_tree
      dict__parent[package_name] = {
        "version": version,
        "date": date,
        "dependencies": {}
      }
      for dependency in dependencies:
        find__package__and__parse__dpendencies(
          dependency, 
          str__version_target=None, 
          str__date_before=date, 
          dict__parent=dict__parent[package_name]
        )
    else: # sub dependencies
      dict__parent["dependencies"][package_name] = {
        "version": version,
        "date": date,
        "dependencies": {}
      }
      for dependency in dependencies:
        find__package__and__parse__dpendencies(
          dependency, 
          str__version_target=None, 
          str__date_before=date, 
          dict__parent=dict__parent["dependencies"][package_name]
        )
  else:
    error(f"'{package_name}' @ {str__version_target} not found")
    list__error_packages.append({
      "package_name": package_name,
      "version_target": str__version_target,
      "date_before": str__date_before
    })

def command__tree(list_str__package_name__and__version):
  global dict__dependencies_tree
  print("parse dependencies tree...")

  for str__package_name__and__version in list_str__package_name__and__version:
    package_name, str__version_target = split__package_name__and__version(str__package_name__and__version)

    find__package__and__parse__dpendencies(
      package_name = package_name,
      str__version_target = str__version_target,
      str__date_before = None, 
      dict__parent = dict__dependencies_tree
    )

  success("dependencies tree parsed\n")
  print(dict__dependencies_tree)
  save__file(os.path.join(PATH_CACHE, f"{formatted_date__when_start}_dependencies_tree.json"), json.dumps(dict__dependencies_tree, ensure_ascii=False, indent=2))

  if len(list__error_packages) > 0:
    error("but with some packages not found:")
    print(f"  {list__error_packages}")
    save__file(os.path.join(PATH_CACHE, f"{formatted_date__when_start}_error_packages.json"), json.dumps(list__error_packages, ensure_ascii=False, indent=2))

  # sort out packages and order to install
  
  def organize_dict(dict__nested):
    list__result = []
    def append__packages__in(dict, int__level=0):
      if len(dict) > 0:
        for key in dict:
          list__result.append((int__level, key, dict[key]["version"], dict[key]["date"]))
          if "dependencies" in dict[key]:
            if len(dict[key]["dependencies"]) > 0:
              append__packages__in(dict[key]["dependencies"], int__level + 1)
    append__packages__in(dict__nested)
    sorted_result = sorted(list__result, key=lambda x: x[0], reverse=True)
  
    dict__final = {}

    for tmp in sorted_result:
      if tmp[1] not in dict__final:
        dict__final[tmp[1]] = {
          "priority": tmp[0],
          "version": tmp[2],
          "date": tmp[3]
        }
      else:
        tmp_priority = tmp[0]
        if tmp_priority > dict__final[tmp[1]]["priority"]:
          dict__final[tmp[1]]["priority"] = tmp_priority
        
        tmp_version = tmp[2]
        tmp_date = tmp[3]
        date__tmp = datetime.strptime(tmp_date, "%Y-%m-%d")
        date__final = datetime.strptime(dict__final[tmp[1]]["date"], "%Y-%m-%d")
        if date__tmp < date__final:
          dict__final[tmp[1]]["version"] = tmp_version
          dict__final[tmp[1]]["date"] = tmp_date

    return dict__final

  dict__final = organize_dict(dict__dependencies_tree)
  save__file(os.path.join(PATH_CACHE, f"dependencies_tree_final_{formatted_date__when_start}.json"), json.dumps(dict__final, ensure_ascii=False, indent=2))

  return dict__final

def command__add(list_str__package_name__and__version):
  dict__dependencies_tree = command__tree(list_str__package_name__and__version)

  # turn dict into list sorted by priority from high to low
  list__sorted = sorted(dict__dependencies_tree.items(), key=lambda x: x[1]["priority"], reverse=True)

  for element in list__sorted:
    # print(element)
    print(f"installing {element[0]} @ {element[1]['version']} ...")
    
    path__R_package = os.path.join(PATH_STORAGE, f"{element[0]}_v_{element[1]['version']}.tar.gz")
    print(f"  from {path__R_package}")
    
    list__R_command = [
      "R",
      "-e",
      f"install.packages('{path__R_package}', repos = NULL)"
    ]

    try:
      with open("./process.log", "a") as log_file:
        subprocess.run(list__R_command, check=True, stdout=log_file, stderr=log_file)
      success("  package installed")
    except Exception as e:
      error(f"package installation failed: {e}")

def handle__command_error():
  error("input format can not be parsed")
  print(
    "\nusage:\n" + 
    "  python uppair.py [command] [args separated by space]\n" + 
    "[command]\n" + 
    "  auto\t| no args needed\t\t| parse ./renv.json , auto install to current R env\n" + 
    "  add\t| [...pack@ver]\t\t\t| add package(s) to current R env\n" + 
    "  tree\t| [R version] [...pack@ver]\t| parse dependencies of package(s) limited by R version"
  )
  exit(1)

def route__command(command, params):
  global str__R_version
  # print(f"\ncommand:\n  {command}\nparams:\n  {params}")
  if command == "auto":
    # TODO
    pass
  elif command == "add":
    list_str__package_name__and__version = params[1:]
    
    if__task_confirmed = ask__user_confirm(f"confirm task: add R packages: {list_str__package_name__and__version} ?")

    if if__task_confirmed:
      command__add(list_str__package_name__and__version)
    else:
      warning("operation canceled")
      exit(1)
  elif command == "tree":
    str__R_version = params[0].strip()
    list_str__package_name__and__version = params[1:]

    if__task_confirmed = ask__user_confirm(f"confirm task: parse dependencies of {list_str__package_name__and__version} limited by R version {str__R_version} ?")
    
    if if__task_confirmed:
      command__tree(list_str__package_name__and__version)
    else:
      warning("operation canceled")
      exit(1)
  else:
    error(f"unrecognized command: '{command}'")
    handle__command_error()
  success("all done!")

if __name__ == "__main__":
  print("checking directories...")
  os.makedirs(PATH_CACHE, exist_ok=True)
  os.makedirs(PATH_STORAGE, exist_ok=True)
  print("directories checked")

  formatted_date__when_start = get__fotmatted_date()
  initialize__RE()

  # handle **arguments input by command line**
  args = sys.argv
  if len(args) < 2: # `args[0]` is `"uppair.py"`
    handle__command_error()
  route__command(args[1], args[2:])

# test code:
# python ./uppair.py tree 4.2.1 NPCD@1.0-11 CDM@7.5-15 GDINA@2.8.8
# python ./uppair.py add NPCD@1.0-11 CDM@7.5-15 GDINA@2.8.8