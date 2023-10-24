# Python do-it file for managing FINN, the Finn-cpp-driver and running synthesis jobs
# Work in progress!

import subprocess
import sys
import os
import json
import platform
import copy
import toml
from doit.action import CmdAction

#* Import configuration
config = None
with open("finn_noctua_install_config.toml", "r") as f:
    config = toml.loads(f.read())
if config is None:
    print("Failed to read config file! Check for syntax errors!")
    sys.exit()


#* DOIT Configuration
DOIT_CONFIG = {"action_string_formatting": "new", "default_tasks": ["finn-doit-setup"]}

# TODO: Implement possibility to specify board and part numbers here

#* TASK Configuration 
environment = config["general"]["used_environment"]
dev_mode = config["general"]["dev_mode"]
driver_required_commands = config["environment"][environment]["driver_compiler_prefix_commands"]
job_exec_prefix = config["environment"][environment]["job_execution"]

finn_build_script = config["environment"][environment]["finn_build_script"]
cppdriver_run_script = config["environment"][environment]["cppdriver_run_script"]
pythondriver_run_script = config["environment"][environment]["pythondriver_run_script"]

finn_repos = config["finn"]["repositories"]
finn_default_repo_name = config["finn"]["default_repository"]
finn_default_repo = finn_repos[finn_default_repo_name]
finn_default_branch = config["finn"]["default_branch"]
finn_build_template = config["finn"]["build_template"]

finndriver_default_repo = config["finn_driver"]["default_repository"]
finndriver_default_branch = config["finn_driver"]["default_branch"]
finndriver_default_compilemode = config["finn_driver"]["default_compile_mode"]

# The folder which _contains_ finn, FINN_TMP, SINGULARITY_CACHE, etc.
os.environ["FINN_WORKDIR"] = os.path.abspath(os.getcwd())

# The path to the GHA, which builds the singularity/apptainer image
os.environ["FINN_SINGULARITY"] = config["general"]["finn_singularity_gha"]

# Insert a name to use the given task as a subtask
def decorate_with_name(task):
    name = task.__name__.replace("task_", "")
    t = task()
    t.update({"name": "subtask-" + name})
    return t


# * SETUP
def task_finn_doit_setup():
    td = ["getfinn"]
    # Only download the driver and its dependencies as well, if the dev mode is active, to save time for normal users
    if dev_mode:
        td += ["getfinndriver", "dmkbuildfolder"]
    
    yield {
        "basename": "finn-doit-setup",
        "doc": "Does a first time setup install finn, finn-cpp-driver and creating an envinfo.json, containing user data",
        "task_dep": td,
        "actions": []
    }


# * CLONE FINN
def task_getfinn():
    def clone(source):
        # TODO: Solve this using doit's choice system
        if source not in finn_repos.keys():
            print("Invalid source repo! Valid choices are: " + str(finn_repos.keys()))
            sys.exit()

        if os.path.isdir("finn"):
            return

        cmd = "git clone " + finn_repos[source]
        subprocess.run(cmd, shell=True, stdout=subprocess.PIPE)
        

    def renameIfEki():
        if os.path.isdir("finn-internal"):
            os.rename("finn-internal", "finn")

    def initSubmodules():
        subprocess.run("git submodule init;git submodule update", shell=True, stdout=subprocess.PIPE, cwd="finn")

    return {
        "doc": "Clone the specified repository and switch to a given branch. Should only be executed once",
        "params": [
            {
                "name": "branch",
                "long": "branch",
                "short": "b",
                "type": str,
                "default": finn_default_branch,
            },
            {
                "name": "source",
                "long": "source",
                "short": "s",
                "type": str,
                "default": finn_default_repo_name,
            },
        ],
        "actions": [
            (clone,),
            (renameIfEki,),
            CmdAction("git checkout {branch}", cwd="./finn"),
            (initSubmodules,)
        ],
    }


# * FORCE GIT PULL ON FINN ITSELF
def task_ffupdate():
    return {
        "doc": "FINN forced-update. Overwrite all changes locally and pull form origin",
        "actions": [CmdAction("git pull;git reset --hard;git pull", cwd="finn")],
        "verbosity": 2,
    }


#### FOR FINN PROJECT CREATION ####
def get_project_dir_name(name):
    #! This expects a LIST (as pos_arg from doit)
    pname = os.path.basename(name[0]).replace(".onnx", "")
    pdir = os.path.join(".", pname)
    return pdir, pname


def purge_old_builds_func(builddir: str, purge_older_builds: bool):
    if purge_older_builds:
        # TODO
        pass

def create_project_dir_if_needed(name):
    pdir, pname = get_project_dir_name(name)
    if not os.path.isdir(pdir):
        os.mkdir(pdir)
        print("Created project folder under the path " + pdir)
    purge_old_builds_func(pdir, True)


def copy_onnx_file(name):
    pdir, pname = get_project_dir_name(name)
    if not os.path.isfile(os.path.join(pdir, pname + ".onnx")):
        subprocess.run(f"cp {name[0]} {pdir}", shell=True)


def inst_build_template(name):
    pdir, pname = get_project_dir_name(name)
    basename = pname + ".onnx"
    if not os.path.isfile(os.path.join(pdir, "build.py")):
        subprocess.run(f"cp {finn_build_template} {pdir}", shell=True)
        subprocess.run(f"mv {finn_build_template} build.py", cwd=pdir, shell=True)
        subprocess.run(
            f'sed -i -e "s/<ONNX_INPUT_NAME>/{basename}/g" build.py',
            cwd=pdir,
            shell=True,
        )  # ? Ugly string manipulation, improve at some point
        print("build.py templated! Please edit the build.py to your liking.")


# * MAKE FINN PROJECT FOLDER
def task_fmkproject():
    return {
        "doc": "Create a finn project folder. Only executes the different steps, depending on whether they are needed",
        "actions": [
            (create_project_dir_if_needed,),
            (copy_onnx_file,),
            (inst_build_template,),
        ],
        "pos_arg": "name",
        "verbosity": 2,
    }


# TODO: Update with replacement of make.sh script
# TODO: Executes regardless of dependencies right now. Fix that
def task_finn():
    def run_synth_for_onnx_name(name):
        pname = os.path.basename(name[0]).replace(".onnx", "")
        basename = pname + ".onnx"
        pdir = os.path.join(".", pname)
        subprocess.run(f"{job_exec_prefix}{finn_build_script} {os.path.abspath(pdir)}", shell=True)

    return {
        "doc": "Execute a finn compilation and synthesis.",
        "pos_arg": "name",
        "actions": [
            (create_project_dir_if_needed,),
            (copy_onnx_file,),
            (inst_build_template,),
            (run_synth_for_onnx_name,),
        ],
        "verbosity": 2,
    }


# TODO: Only test for now, change that
# * RUN PYTHON DRIVER IF EXISTING
def task_pythondriver():
    def run_python_driver(arg):
        pdir, pname = get_project_dir_name(arg)
        if not os.path.isdir(pdir):
            print("No project directory found under the name " + pname + " and path " + os.path.abspath(pdir))
        output_dirs = [x for x in os.listdir(pdir) if x.startswith("out_")]
        if len(output_dirs) == 0:
            print(
                "Project with input name "
                + pname
                + " has no output folder! (Searched in "
                + os.path.abspath(pdir)
                + ")"
            )
        driver_dir = os.path.join(os.path.abspath(pdir), output_dirs[0], "deploy", "driver")
        subprocess.run(
            f"{job_exec_prefix}{run_python_driver} {driver_dir}",
            shell=True,
        )

    return {
        "doc": "Execute the python driver of a project, print the results on screen",
        "pos_arg": "arg",
        "actions": [(run_python_driver,)],
        "verbosity": 2,
    }


# * MAKE BUILD FOLDER FOR FINN COMPILER
def task_dmkbuildfolder():
    def remake_build_folder():
        bdir = os.path.join("finn-cpp-driver", "build")
        if os.path.isdir(bdir):
            subprocess.run(f"rm -rf {bdir}", shell=True, stdout=subprocess.PIPE)
        os.mkdir(bdir)

    return {
        "actions": [(remake_build_folder,)],
        "doc": "Delete and remake the finn-cpp-driver/build folder. Does NOT call cmake for config!",
    }


# * CLONE FINN C++ DRIVER
def task_getfinndriver():
    def clone(branch):
        if os.path.isdir("finn-cpp-driver"):
            return

        subprocess.run(
            f"git clone {finndriver_default_repo}",
            shell=True,
            cwd=".",
        )
        subprocess.run(f"git checkout {branch}", shell=True, cwd="./finn-cpp-driver")
        subprocess.run("git submodule init;git submodule update", shell=True, stdout=subprocess.PIPE, cwd="finn-cpp-driver")
        subprocess.run(
            "./buildDependencies.sh",
            shell=True,
            cwd="./finn-cpp-driver",
        )

    return {
        "doc": "Clone the finn-cpp-driver git repository and run the setup script",
        "params": [
            {
                "name": "branch",
                "long": "branch",
                "short": "b",
                "type": str,
                "default": finndriver_default_branch,
            }
        ],
        "actions": [(clone,)],
        "targets": ["finn-cpp-driver/buildDependencies.sh"],
    }


# * FORCE GIT PULL ON FINN DRIVER
def task_dfupdate():
    return {
        "doc": "Driver forced-update. Overwrite all changes locally and pull form origin",
        "actions": [CmdAction("git pull;git reset --hard;git pull", cwd="finn-cpp-driver")],
        "verbosity": 2,
    }


# * EXECUTE FINNBOOST BUILD DEPENDENCIES SCRIPT
def task_dbuilddeps():
    return {
        "doc": "Execute the buildDependencies script to build FinnBoost for the driver. Needs to be done once before compiling for the first time. [This task is never executed automatically]",
        "actions": [
            CmdAction(
                "./buildDependencies.sh",
                cwd="finn-cpp-driver",
            )
        ],
    }


# * COMPILE FINN DRIVER
# TODO: take the name of the project as pos_arg, so that the config.json and Finn.h header can be read directly from the project directory
def task_dcompile():
    return {
        "params": [
            {
                "name": "mode",
                "long": "mode",
                "short": "m",
                "type": str,
                "default": finndriver_default_compilemode,
            }
        ],
        "doc": "Compile the FINN C++ driver in the given mode",
        "targets": ["finn-cpp-driver/build/src/finn"],
        "actions": [
            CmdAction("cmake -DCMAKE_BUILD_TYPE={mode} ..", cwd="finn-cpp-driver/build"),
            CmdAction("cmake --build . --target finn", cwd="finn-cpp-driver/build"),
        ],
        "task_dep": ["dmkbuildfolder"],
        "verbosity": 2,
    }


def task_cppdriver():
    def run_cpp_driver(mode, name):
        outdirs = [x for x in os.listdir(get_project_dir_name(name)) if x.startswith("out")]
        if len(outdirs) == 0:
            print("No output folder available to run driver from. Please finish a FINN compilation first!")
            sys.exit()
        if mode == "test":
            # TODO: Currently if only testing the input parameter has to be filled with an existing file. Fix this
            print("Running driver now!")
            driver_dir = os.path.join(get_project_dir_name(name), outdirs[0], "driver")
            subprocess.run(
                f"{job_exec_prefix}{run_cpp_driver} {driver_dir}",
                shell=True,
            )
            print("Finished running driver!")
        else:
            print("NOT IMPLEMENTED")
            sys.exit()

    return {
        "params": [
            {
                "name": "mode",
                "long": "mode",
                "short": "m",
                "type": str,
                "default": "test",
            }
        ],
        "pos_arg": "name",
        "doc": 'Run the driver of the finished compiled FINN project of the given name. This requires that the results of the compilation are found in a directory starting with "out", which has to contain the bitfile in bitfile/ and the finn executable and the config json in driver/. If multiple dirs with out are given, the first sorted is used',
        "actions": [(run_cpp_driver,)],
        "verbosity": 2,
    }
