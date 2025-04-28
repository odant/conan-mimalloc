from conan import ConanFile, tools
from conan.tools.cmake import CMake, CMakeToolchain, CMakeDeps, cmake_layout
from conan.errors import ConanInvalidConfiguration, ConanException
from conan.tools import build, microsoft, scm, env, files  

import os, shutil, functools

class MimallocConan(ConanFile):
    version = "2.1.9+0"
    name = "mimalloc"
    license = "MIT"
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://github.com/microsoft/mimalloc"
    description = "mimalloc is a compact general purpose allocator with excellent performance."
    topics = ("conan", "mimalloc", "allocator", "performance", "microsoft")
    settings = "os", "compiler", "build_type", "arch"
    options = {
        "dll_sign": [True, False],
        "shared": [True, False],
        "fPIC": [True, False],
        "secure": [True, False],
        "override": [True, False],
        "inject": [True, False],
        "single_object": [True, False]
    }
    default_options = {
        "dll_sign": False,
        "shared": True,
        "fPIC": True,
        "secure": False,
        "override": True,
        "inject": False,
        "single_object": False
    }
    exports_sources = "src/*"
    no_copy_source = False
    build_policy = "missing"
    package_type = "library"
    python_requires = "windows_signtool/[>=1.2]@odant/stable"

    @property
    def _source_subfolder(self):
        return "src"
    @property
    def _build_subfolder(self):
        return "build"

    @property
    def _compilers_minimum_version(self):
        return {
            "gcc": "7",
            "msvc": "191",
            "clang": "5",
            "apple-clang": "10",
        }

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC
        else:
            del self.options.dll_sign

        # single_object and inject are options
        # only when overriding on Unix-like platforms:
        if self.settings.compiler == "msvc":
            del self.options.single_object
            del self.options.inject

    def layout(self):
        cmake_layout(self, src_folder="src") 
        
    def configure(self):
        if self.options.shared:
            self.options.rm_safe("fPIC")

            # single_object is valid only for static
            # override:
            if self.options.get_safe("single_object"):
                del self.options.single_object

        # inject is valid only for Unix-like dynamic override:
        if not self.options.shared and self.options.get_safe("inject"):
            del self.options.inject

        # single_object and inject are valid only when
        # overriding on Unix-like platforms:
        if not self.options.override:
            if self.options.get_safe("single_object"):
                del self.options.single_object
            if self.options.get_safe("inject"):
                del self.options.inject

    def validate(self):
        # Currently, mimalloc/1.7.6,2.0.6 does not work properly with shared MD builds.
        # https://github.com/conan-io/conan-center-index/pull/10333#issuecomment-1114110046
        if  self.version in ["1.7.6", "2.0.6"] and \
            self.options.shared and \
            microsoft.is_msvc(self) and \
            "MD" in microsoft.msvc_runtime_flag(self):
            raise ConanInvalidConfiguration(
                "Currently, mimalloc/1.7.6,2.0.6 doesn't work properly with shared MD builds.")

        # Shared overriding requires dynamic runtime for MSVC:
        if self.options.override and \
           self.options.shared and \
           microsoft.is_msvc(self) and \
           "MT" in microsoft.msvc_runtime_flag(self):
            raise ConanInvalidConfiguration(
                "Dynamic runtime (MD/MDd) is required when using mimalloc as a shared library for override")

        if self.options.override and \
           self.options.get_safe("single_object") and \
           self.options.get_safe("inject"):
            raise ConanInvalidConfiguration("Single object is incompatible with library injection")

        if self.settings.compiler.get_safe("cppstd"):
            build.check_min_cppstd(self, "17")

        minimum_version = self._compilers_minimum_version.get(str(self.settings.compiler), False)

        if not minimum_version:
            self.output.warning("mimalloc requires C++17. Your compiler is unknown. Assuming it supports C++17.")
        elif scm.Version(self.settings.compiler.version) < minimum_version:
            raise ConanInvalidConfiguration("mimalloc requires a compiler that supports at least C++17")

    def build_requirements(self):
        self.tool_requires("ninja/[>=1.12.1]")
        if self.options.get_safe("dll_sign"):
            self.tool_requires("windows_signtool/[>=1.2]@%s/stable" % self.user)

    def generate(self):
        envir = env.VirtualBuildEnv(self);
        envir.generate();
        
        if microsoft.is_msvc(self):
            vcvars = microsoft.VCVars(self);
            vcvars.generate();
        
        tc = CMakeToolchain(self, generator="Ninja")
        tc.variables["MI_BUILD_TESTS"] = "OFF"
        tc.variables["MI_BUILD_SHARED"] = self.options.shared
        tc.variables["MI_BUILD_STATIC"] = not self.options.shared
        tc.variables["MI_BUILD_OBJECT"] = self.options.get_safe("single_object", False)
        tc.variables["MI_OVERRIDE"] = "ON" if self.options.override else "OFF"
        tc.variables["MI_SECURE"] = "ON" if self.options.secure else "OFF"
        tc.variables["MI_INSTALL_TOPLEVEL"] = "ON"
        tc.generate()
            
    def build(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        files.copy(self, "LICENSE", dst=os.path.join(self.package_folder, "licenses"), src=os.path.join(self.source_folder, "src"))
        cmake = CMake(self)
        cmake.install()

        clean_dirs = [
            os.path.join(self.package_folder, "lib", "cmake"),
            os.path.join(self.package_folder, "lib", "pkgconfig")
        ]
        for d in clean_dirs:
            if os.path.isdir(d):
                shutil.rmtree(d) 
                
        if self.options.get_safe("single_object"):
            tools.remove_files_by_mask(os.path.join(self.package_folder, "lib"),
                                       "*.a")
            shutil.move(os.path.join(self.package_folder, self._obj_name + ".o"),
                        os.path.join(self.package_folder, "lib"))
            shutil.copy(os.path.join(self.package_folder, "lib", self._obj_name + ".o"),
                        os.path.join(self.package_folder, "lib", self._obj_name))

        # Sign DLL
        if self.options.get_safe("dll_sign"):
            self.python_requires["windows_signtool"].module.sign(self, [os.path.join(self.package_folder, "bin", "*.dll")])

    @property
    def _obj_name(self):
        name = "mimalloc"
        if self.options.secure:
            name += "-secure"
        if self.settings.build_type not in ("Release", "RelWithDebInfo", "MinSizeRel"):
            name += "-{}".format(str(self.settings.build_type).lower())
        return name

    def package_info(self):
        if self.options.get_safe("inject"):
            self.cpp_info.includedirs = []
            self.cpp_info.libdirs = []
            self.cpp_info.resdirs = []
            return

        if self.options.get_safe("single_object"):
            obj_ext = "o"
            obj_file = "{}.{}".format(self._obj_name, obj_ext)
            obj_path = os.path.join(self.package_folder, "lib", obj_file)
            self.cpp_info.exelinkflags = [obj_path]
            self.cpp_info.sharedlinkflags = [obj_path]
            self.cpp_info.libdirs = []
            self.cpp_info.bindirs = []
        else:
            self.cpp_info.libs = files.collect_libs(self)

        if self.settings.os == "Linux":
            self.cpp_info.system_libs.append("pthread")
        if not self.options.shared:
            if self.settings.os == "Windows":
                self.cpp_info.system_libs.extend(["psapi", "shell32", "user32", "bcrypt"])
            elif self.settings.os == "Linux":
                self.cpp_info.system_libs.append("rt")
