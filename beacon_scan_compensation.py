import logging, collections
from . import bed_mesh as BedMesh


class BeaconScanCompensation:
    def __init__(self, config):
        self.config = config
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.gcode = self.printer.lookup_object('gcode')
        self.reactor = self.printer.get_reactor()
        self.bed_mesh = None

        self.gcode.register_command(
            "BEACON_APPLY_SCAN_COMPENSATION",
            self.cmd_BEACON_APPLY_SCAN_COMPENSATION,
            desc=self.cmd_BEACON_APPLY_SCAN_COMPENSATION_help,
        )
        self.pmgr = BedMeshProfileManager(self.config, self)

    def _connect(self):
        if self.config.has_section("bed_mesh"):
            self.bed_mesh = self.printer.lookup_object('bed_mesh')

    cmd_BEACON_APPLY_SCAN_COMPENSATION_help = "Compensates magnetic inaccuracies for beacon scan meshes."

    def cmd_BEACON_APPLY_SCAN_COMPENSATION(self, gcmd):
        profile = gcmd.get('PROFILE', "Contact")
        if not profile.strip():
            raise gcmd.error(
                "Value for parameter 'PROFILE' must be specified")
        if profile not in self.pmgr.get_profiles():
            raise self.printer.command_error("Profile " + str(
                profile) + " not found for Beacon scan compensation")
        self.contact_mesh = self.pmgr.load_profile(profile)
        if not self.contact_mesh:
            raise self.printer.command_error(
                "Could not load profile " + str(
                    profile) + " for Beacon scan compensation")
        self.compensate_beacon_scan(profile)

    #####
    # Beacon Scan Compensation
    #####
    def compensate_beacon_scan(self, profile):
        systime = self.reactor.monotonic()
        try:
            if self.bed_mesh.z_mesh:
                profile_name = self.bed_mesh.z_mesh.get_profile_name()
                if profile_name != profile:
                    points = \
                        self.bed_mesh.get_status(systime)["profiles"][
                            profile_name][
                            "points"]
                    params = self.bed_mesh.z_mesh.get_mesh_params()
                    x_step = ((params["max_x"] - params["min_x"]) / (
                            len(points[0]) - 1))
                    y_step = ((params["max_y"] - params["min_y"]) / (
                            len(points) - 1))
                    new_points = []
                    for y in range(len(points)):
                        new_points.append([])
                        for x in range(len(points[0])):
                            x_pos = params["min_x"] + x * x_step
                            y_pos = params["min_y"] + y * y_step
                            z_val = points[y][x]
                            contact_z = self.contact_mesh.calc_z(x_pos,
                                                                 y_pos)
                            new_z = z_val - (z_val - contact_z)
                            new_points[y].append(new_z)
                    self.bed_mesh.z_mesh.build_mesh(new_points)
                    self.bed_mesh.save_profile(profile_name)
                    self.bed_mesh.set_mesh(self.bed_mesh.z_mesh)
                    self.gcode.run_script_from_command(
                        "CONSOLE_ECHO TYPE=debug TITLE='Beacon scan compensation' MSG='Mesh scan profile " + str(
                            profile_name) + " compensated with contact profile " + str(
                            profile) + "'")
        except BedMesh.BedMeshError as e:
            self.gcode.run_script_from_command(
                "CONSOLE_ECHO TYPE=error TITLE='Beacon scan compensation error' MSG='" + str(
                    e) + "'")


class BedMeshProfileManager:
    def __init__(self, config, bedmesh):
        self.name = "bed_mesh"
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.bedmesh = bedmesh
        self.profiles = {}
        self.incompatible_profiles = []
        # Fetch stored profiles from Config
        stored_profs = config.get_prefix_sections(self.name)
        stored_profs = [s for s in stored_profs
                        if s.get_name() != self.name]
        for profile in stored_profs:
            name = profile.get_name().split(' ', 1)[1]
            version = profile.getint('version', 0)
            if version != BedMesh.PROFILE_VERSION:
                logging.info(
                    "bed_mesh: Profile [%s] not compatible with this version\n"
                    "of bed_mesh.  Profile Version: %d Current Version: %d "
                    % (name, version, BedMesh.PROFILE_VERSION))
                self.incompatible_profiles.append(name)
                continue
            self.profiles[name] = {}
            zvals = profile.getlists('points', seps=(',', '\n'), parser=float)
            self.profiles[name]['points'] = zvals
            self.profiles[name]['mesh_params'] = params = \
                collections.OrderedDict()
            for key, t in BedMesh.PROFILE_OPTIONS.items():
                if t is int:
                    params[key] = profile.getint(key)
                elif t is float:
                    params[key] = profile.getfloat(key)
                elif t is str:
                    params[key] = profile.get(key)

    def get_profiles(self):
        return self.profiles

    def load_profile(self, prof_name):
        profile = self.profiles.get(prof_name, None)
        if profile is None:
            return None
        probed_matrix = profile['points']
        mesh_params = profile['mesh_params']
        z_mesh = BedMesh.ZMesh(mesh_params, prof_name)
        try:
            z_mesh.build_mesh(probed_matrix)
        except BedMesh.BedMeshError as e:
            raise self.gcode.error(str(e))
        return z_mesh


def load_config(config):
    return BeaconScanCompensation(config)
