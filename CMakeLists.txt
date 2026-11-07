cmake_minimum_required(VERSION 3.16)

# sdkconfig.local (non versionato) contiene Wi-Fi e URL del servizio: vedi sdkconfig.local.example
set(SDKCONFIG_DEFAULTS "sdkconfig.defaults")
if(EXISTS "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.local")
    list(APPEND SDKCONFIG_DEFAULTS "sdkconfig.local")
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(smart_speaker)
