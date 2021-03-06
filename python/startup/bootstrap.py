# Copyright (c) 2014 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.


import sgtk
from sgtk import TankError
import os
import re
import sys

def _get_flame_version(flame_path):
    """
    Returns the version string for the given Flame path
    
    /usr/discreet/flameassist_2015.2/bin/startApplication        --> (2015, 2, "2015.2")
    /usr/discreet/flameassist_2015.3/bin/startApplication        --> (2015, 3, "2015.3")
    /usr/discreet/flameassist_2016.0.0.322/bin/startApplication  --> (2016, 0, "2016.0.0.322")
    /usr/discreet/flameassist_2015.2.pr99/bin/startApplication   --> (2015, 2, "2015.2.pr99")
    /usr/discreet/flameassist_2016.pr50/bin/startApplication     --> (2016, 0, "2016.pr50")
    
    If the minor or major version cannot be extracted, it will be set to zero.
    
    :param flame_path: path to executable
    :returns: (major, minor, full_str)
    """

    # do a quick check to ensure that we are running 2015.2 or later
    re_match = re.search("/fla[mr]e[^_]*_([^/]+)/", flame_path)
    if not re_match:
        raise TankError("Cannot extract Flame version number from the path '%s'!" % flame_path)
    version_str = re_match.group(1)
    
    # Examples:
    # 2015.2
    # 2016
    # 2016.pr99
    # 2015.2.pr99
    
    major_ver = 0
    minor_ver = 0
    
    chunks = version_str.split(".")
    if len(chunks) > 0:
        if chunks[0].isdigit():
            major_ver = int(chunks[0])
    
    if len(chunks) > 1:
        if chunks[1].isdigit():
            minor_ver = int(chunks[1])

    return (major_ver, minor_ver, version_str)
    

def bootstrap(engine_instance_name, context, app_path, app_args):
    """
    Entry point for starting this engine.
    This is typically called from something like tk-multi-launchapp
    prior to starting up the DCC, but could be initialized in other ways too.
    
    This method needs to be able to execute from any python version, with 
    or without QT installed. Since it will typically be executed from within
    the multi-launch-app, it will be running in the python that was used to 
    start the engine where the multi-launch-app is running (typically 
    tk-shell/tk-desktop/tk-shotgun). 

    The purpose of this script is to prepare the launch process for Flame,
    return the executable that the launch app should actually execute. This 
    process consists of an additional step for Flame because part of the app
    launch process happens outside of Flame. We therefore rewrite the launch
    arguments as part of this method. For example
    
    input: app_path: /usr/discreet/flame_2015.2/bin/startApplication
           app_args: --extra args
    
    output: app_path: /usr/discreet/Python-2.6.9/bin/python
            app_args: /mnt/software/shotgun/my_project/install/engines/app-store/tk-flame/v1.2.3/python/startup/launch_app.py 
                      /usr/discreet/flame_2015.2/bin/startApplication 
                      --extra args
    
    :param engine_instance_name: the name of the engine instance in the environment to launch
    :param context: The context to launch
    :param app_path: The path to the DCC to start
    :param app_args: External args to pass to the DCC 

    :returns: (app_path, app_args)
    """
    # do a quick check to ensure that we are running 2015.2 or later
    (major_ver, minor_ver, version_str) = _get_flame_version(app_path)
    
    if major_ver < 2015:
        raise TankError("In order to run the Shotgun integration, you need at least Flame 2015, extension 2!")
    
    if major_ver == 2015 and minor_ver < 2:
        raise TankError("In order to run the Shotgun integration, you need at least Flame 2015, extension 2!")
    
    # first of all, check that the executable path to Flame exists
    if not os.path.exists(app_path):
        raise TankError("Cannot launch Flame - the path '%s' does not exist on disk!" % app_path)
    
    # update the environment prior to launch
    os.environ["TOOLKIT_ENGINE_NAME"] = engine_instance_name
    os.environ["TOOLKIT_CONTEXT"] = sgtk.context.serialize(context)
        
    # ensure that we add the right location for the wiretap API.
    # on 2016 and above, we can use the one distributed with Flame
    # on 2015 ext2 and ext3, this version is not working and we instead
    # use a version specifically distributed with the engine.     
    # in 2016: /usr/discreet/flameassist_2016.0.0.322/python
    
    wiretap_path = None
    
    if major_ver == 2015:
        this_folder = os.path.abspath(os.path.dirname(__file__))
        engine_root = os.path.abspath(os.path.join(this_folder, "..", ".."))
        if sys.platform == "linux2":
            wiretap_path = os.path.join(engine_root, "resources", "wiretap", "2015", "linux")                
        elif sys.platform == "darwin":
            wiretap_path = os.path.join(engine_root, "resources", "wiretap", "2015", "macosx")
        else:
            raise TankError("Unsupported platform for the wiretap API!")
        
    else:
        # grab /usr/discreet/flameassist_2016.0.0.322 part of the path and then append python
        
        # do some checks here - in case clients have special launch scripts they want to use
        # we may have to alter this logic for finding the python libs. But until we get that 
        # feedback from clients, let's go with the simple approach where we extract the location
        # from the launch path.
        if not app_path.startswith("/usr/discreet/"):
            raise TankError("Invalid application path '%s'. This needs to start with /usr/discreet" % app_path)
        
        path_chunks = app_path.split("/")[:4]        
        path_chunks.append("python")
        wiretap_path = "/".join(path_chunks)

    sgtk.util.prepend_path_to_env_var("PYTHONPATH", wiretap_path)
    
    # also, in order to ensure that QT is working correctly inside of
    # the Flame python interpreter, we need to hint the library order
    # by adjusting the LD_LIBRARY_PATH. Note that this cannot be done
    # inside an executing script as the dynamic loader sets up the load
    # order prior to the execution of any payload. This is why we need to 
    # set this before we run the app launch script.
    if sys.platform == "darwin":
        # add system libraries
        sgtk.util.prepend_path_to_env_var("DYLD_FRAMEWORK_PATH", "/usr/discreet/lib64/%s/framework" % version_str)
        
    elif sys.platform == "linux2":
        # add python related libraries
        if major_ver == 2015:
            # on Flame 2015, this is stored in the python lib location
            sgtk.util.prepend_path_to_env_var("LD_LIBRARY_PATH", "/usr/discreet/Python-2.6.9/lib")
        else:
            # on Flame 2016, each version is managed separately
            sgtk.util.prepend_path_to_env_var("LD_LIBRARY_PATH", "/usr/discreet/python/%s/lib" % version_str)
        
        # add system libraries
        sgtk.util.prepend_path_to_env_var("LD_LIBRARY_PATH", "/usr/discreet/lib64/%s" % version_str)
    
    # figure out the python location
    if major_ver == 2015:
        python_binary = "/usr/discreet/Python-2.6.9/bin/python"
        
    else:
        python_binary = "/usr/discreet/python/%s/bin/python" % version_str
        
    # we need to pass the Flame version into the engine so that this
    # can be picked up at runtime in the Flame. This is in order for
    # the engine to resolve the path to python.
    os.environ["TOOLKIT_FLAME_PYTHON_BINARY"] = python_binary
    
    # also pass the version of Flame in the same manner
    os.environ["TOOLKIT_FLAME_MAJOR_VERSION"] = str(major_ver)
    os.environ["TOOLKIT_FLAME_MINOR_VERSION"] = str(minor_ver)
    os.environ["TOOLKIT_FLAME_VERSION"] = version_str
    
    # the app_launcher.py script is in the same folder as this file
    this_folder = os.path.abspath(os.path.dirname(__file__))
    launch_script = os.path.join(this_folder, "app_launcher.py") 
    
    # finally, reroute the executable and args and return them
    # (see docstring for details)
    new_app_path = python_binary
    new_app_args = "%s %s %s" % (launch_script, app_path, app_args)
    
    return (new_app_path, new_app_args) 
