import os
from os.path import join as pjoin
import scipy.io as sio
from .core import DataPaths, Logger
from .dbinterface import DataBaseInterface
from ..utils import *
from ..gsheet_functions import GSheet


class SessionMeta:
    """An object to hold Session meta data"""

    def __init__(self, prot_file: str = None, init_dict: dict = None, **kwargs) -> None:
        """Initializes the meta either from a prot file or a dictionary that already has the required keys"""
        if init_dict is not None:
            self.init_dict = init_dict
            self.init_from_dict()
        elif prot_file is not None:
            self.prot_file = prot_file
            skip_google = kwargs.get("skip_google", False)
            self.init_from_prot(skip_google=skip_google)

    def __repr__(self):
        kws = [
            f"{key}={value!r}"
            for key, value in self.__dict__.items()
            if key != "init_dict"
        ]
        return "{}\n{}".format(type(self).__name__, ",\n".join(kws))

    def init_from_prot(self, skip_google: bool = False):
        ignore = [
            "picsFolder",
            "picsNameFormat",
            "shuffle",
            "mask",
            "nTrials",
            "progressWindow",
            "debiasingWindow",
            "decimationRatio",
        ]
        self.opto = False
        opts, params = parseProtocolFile(self.prot_file)
        for k, v in opts.items():
            if k not in ignore:
                try:
                    v = float(v.strip(" "))
                except:
                    pass
                setattr(self, k, v)
                if k == "controller":
                    if "Opto" in v:
                        self.opto = True

        if self.opto:
            self.opto_mode = int(opts.get("optoMode", 0))  # 0 continuous, 1 pulsed

        lvl = ""
        if self.prot_file.find("level") != -1:
            tmp = self.prot_file[self.prot_file.find("level") + len("level") :]
            for char in tmp:
                if char not in [".", "_"]:
                    lvl += char
                else:
                    break
        else:
            lvl = "exp"
        self.level = lvl

        self.sf_values = nonan_unique(params["sf"].to_numpy()).tolist()
        self.tf_values = nonan_unique(params["tf"].to_numpy()).tolist()

        self.session_dir = self.prot_file.split(os.sep)[-2]
        self.experiment_name = self.prot_file.split(os.sep)[-1].split(".")[0]

        self.animalid = self.session_dir.split("_")[1]
        self.user = self.session_dir.split("_")[-1]
        self.set_date(self.session_dir.split(os.sep)[-1].split("_")[0])

        self.set_weight_and_water(skip_google=skip_google)
        self.generate_session_id()

    def init_from_dict(self):
        for k, v in self.init_dict.items():
            setattr(self, k, v)

    def set_rig(self, pref_file: str):
        prefs = parsePref(pref_file)
        if "name" in prefs["rig"]:
            self.rig = prefs["rig"]["name"]
        else:
            self.rig = prefs["tmpFolder"].split("\\")[-1]

    def set_date(self, date_str: str):
        self.baredate = date_str
        self.date = dt.strptime(self.baredate, "%y%m%d").date()
        self.nicedate = dt.strftime(self.date, "%d %b %y")

        os_stat = os.stat(self.prot_file)
        if sys.platform == "darwin":
            create_epoch = os_stat.st_birthtime
        elif sys.platform == "win32":
            create_epoch = os_stat.st_ctime
        self.time = dt.fromtimestamp(create_epoch).strftime("%H%M")

    def set_weight_and_water(self, skip_google: bool = False) -> None:
        """Gets the session weight from google sheet"""
        self.weight = None
        self.water_consumed = None
        if not skip_google:
            logsheet = GSheet("Mouse Database_new")
            gsheet_df = logsheet.read_sheet(2)
            gsheet_df = gsheet_df[
                (gsheet_df["Mouse ID"] == self.animalid)
                & (gsheet_df["Date [YYMMDD]"] == int(self.baredate))
            ]
            if not gsheet_df.empty:
                gsheet_df.reset_index(inplace=True)
                self.weight = gsheet_df["weight [g]"].iloc[0]
                try:
                    self.water_consumed = int(gsheet_df["rig water [µl]"].iloc[0])
                except:
                    self.water_consumed = None

    def generate_session_id(self) -> None:
        """Generates a unique session id for the session"""
        try:
            mouse_part = "".join([n for n in self.animalid if n.isdigit()])
            self.session_id = self.baredate + self.time + mouse_part
        except:
            raise RuntimeError(f"Failed to create session id for {self.session_dir}")


class SessionData:
    """The SessionData object is to pass around the session data to plotters and analyzers"""

    __slots__ = ["data", "data_paths", "pattern_imgs", "patterns"]

    def __init__(self) -> None:
        pass

    def set_data(self, data: pl.DataFrame) -> None:
        self.data = data

    def set_paths(self, data_paths: dict) -> None:
        self.data_paths = data_paths

    def save_data(self, save_mat: bool = False) -> None:
        """Saves the session data as .parquet (and .mat file if desired)"""
        self.data.write_parquet(self.data_paths.data)
        display("Saved session data")
        if save_mat:
            self.save_as_mat()
            display("Saving .mat file")

    def load_data(self) -> pd.DataFrame:
        """Loads the data from J:/analysis/<exp_folder> as a pandas data frame"""
        # data = pd.read_csv(self.data_paths.data)
        data = pl.read_parquet(self.data_paths.data)
        self.set_data(data)

    def save_as_mat(self) -> None:
        """Helper method to convert the data into a .mat file"""
        datafile = pjoin(self.data_paths.savePath, "sessionData.mat").replace("\\", "/")
        save_dict = {name: col.values for name, col in self.data.stim_data.items()}
        sio.savemat(datafile, save_dict)
        display(f"Saved .mat file at {datafile}")


class Session:
    """A base Session object to be used in analyzing training/experiment sessions
    :param sessiondir: directory of the session inside the presentation folder(e.g. 200619_KC033_wheel_KC)
    :param load_flag:  flag to either load previously parsed data or to parse it again
    :param save_mat:   flag to make the parser also output a .mat file to be used in MATLAB  scripts
    :type sessiondir:  str
    :type load_flag:   bool
    :type save_mat:    bool
    """

    def __init__(self, sessiondir, load_flag=False, save_mat=False, *args, **kwargs):
        self.sessiondir = sessiondir
        # an empty dictionary that can be populated with session related data
        # every Session object has a meta, session_data and stat attribute
        self.load_flag = load_flag
        self.save_mat = save_mat
        self.logversion = "stimpy"

        # initialize relevant data paths, the log version and the database interface
        self.init_data_paths()

        self.logger = Logger(
            log_path=self.data_paths.analysisPath, append=self.load_flag
        )

        self.db_interface = DataBaseInterface(self.data_paths.config["databasePath"])

    def overall_session_no(self) -> int:
        """Gets the session number of the session"""
        mouse_entry = self.db_interface.get_entries(
            {"id": self.meta.animalid}, table_name="animals"
        )
        if len(mouse_entry):
            last_session_no = mouse_entry["nSessions"].iloc[0]
        else:
            display(f"No entry for mouse {self.meta.animalid} in animals table!")
            last_session_no = 0

        current_session_no = last_session_no + 1
        return current_session_no

    def init_data_paths(self) -> None:
        """Initializes the relevant data paths (log,pref,prot) and creates the savepath"""
        self.data_paths = DataPaths(self.sessiondir)

        if not os.path.exists(self.data_paths.savePath):
            # make dirs
            os.makedirs(self.data_paths.savePath)
            display(
                f"Save path does not exist, created save folder at {self.data_paths.savePath}"
            )

    @staticmethod
    def read_combine_logs(
        stimlog_paths: str | list, riglog_paths: str | list
    ) -> tuple[pl.DataFrame, list]:
        """Reads the logs and combines them if multiple logs of same type exist in the run directory"""
        if isinstance(stimlog_paths, list) and isinstance(riglog_paths, list):
            assert len(stimlog_paths) == len(
                riglog_paths
            ), f"The number stimlog files need to be equal to amount of riglog files {len(stimlog_paths)}=/={len(riglog_paths)}"

            stim_data_all = []
            rig_data_all = []
            stim_comments = []
            rig_comments = []
            for i, s_log in enumerate(stimlog_paths):
                try:
                    temp_slog, temp_scomm = parseStimpyLog(s_log)
                except:
                    # probably not the right stimpy version, try github
                    temp_slog, temp_scomm = parseStimpyGithubLog(s_log)
                temp_rlog, temp_rcomm = parseStimpyLog(riglog_paths[i])
                stim_data_all.append(temp_slog)
                rig_data_all.append(temp_rlog)
                stim_comments.extend(temp_scomm)
                rig_comments.extend(temp_rcomm)

            stim_data = stitchLogs(stim_data_all, isStimlog=True)  # stimlog
            rig_data = stitchLogs(rig_data_all, isStimlog=False)  # riglog
        else:
            try:
                stim_data, stim_comments = parseStimpyLog(stimlog_paths)
            except:
                stim_data, stim_comments = parseStimpyGithubLog(stimlog_paths)
            rig_data, rig_comments = parseStimpyLog(riglog_paths)

        rawdata = {**stim_data, **rig_data}
        comments = stim_comments + rig_comments
        return rawdata, comments

    @timeit("Read data")
    def read_data(self) -> None:
        """Reads the data from concatanated riglog and stimlog files"""
        if self.logversion == "pyvstim":
            self.rawdata, self.comments = parseVStimLog(self.data_paths.log)
        elif self.logversion == "stimpy":
            if len(self.data_paths.runPaths) > 1:
                # multiple runs
                self.rawdata = []
                self.comments = []
                for r in self.data_paths.runPaths:
                    rawdata, comments = self.read_combine_logs(
                        r["stimlog"], r["riglog"]
                    )
                    self.rawdata.append(extrapolate_time(rawdata))
                    self.comments.append(comments)
            elif len(self.data_paths.runPaths) == 1:
                # single run, the stimlog and riglog attributes of the data_paths will point to the run logs
                rawdata, comments = self.read_combine_logs(
                    self.data_paths.stimlog, self.data_paths.riglog
                )
                self.rawdata = [extrapolate_time(rawdata)]
                self.comments = [comments]
        self.logger.info("Read rawdata")

    def extract_trial_count(self):
        """Extracts the trial no from state changes, this works for stimpy for now"""
        display("Trial increment faulty, extracting from state changes...")
        self.states.reset_index(drop=True, inplace=True)
        trial_end_list = self.states.index[self.states["oldState"] == 6].tolist()
        temp_start = 0
        for i, end in enumerate(trial_end_list, 1):
            self.states.loc[temp_start : end + 1, "cycle"] = i
            temp_start = end + 1

    def isSaved(self) -> bool:
        """Initializes the necessary save paths and checks if data already exists"""
        loadable = False
        # the 'stim_pos and 'wheel' columns are saved as lists in DataFrame columns!
        if os.path.exists(self.data_paths.savePath):
            loadable = True
            for r in self.data_paths.dataPaths:
                if os.path.exists(r):
                    tmp_loadable = True
                    self.logger.info(f"Found saved data: {r}", cml=True)
                else:
                    tmp_loadable = False
                    self.logger.info(
                        f"{self.data_paths.savePath} exists but no data file is present...",
                        cml=True,
                    )
                loadable = loadable and tmp_loadable
        else:
            display("THIS SHOULD NOT HAPPEN")
        return loadable

    def save_to_db(self, db_dict: dict) -> None:
        """Checks if an entry for the session already exists and saves/updates accordingly"""
        if not self.db_interface.exists(
            {"sessionId": self.meta.session_id}, "sessions"
        ):
            self.db_interface.add_entry(db_dict, "sessions")
            self.db_interface.update_entry(
                {"id": self.meta.animalid},
                {"nSessions": self.current_session_no},
                "animals",
            )
        else:
            self.db_interface.update_entry(
                {"sessionId": self.meta.session_id}, db_dict, "sessions"
            )
            display(
                f"Session with id {self.meta.session_id} is already in database, updated the entry"
            )

    def get_latest_trial_count(self):
        """Gets the last trial count from"""
        prev_trials = self.db_interface.get_entries(
            {"id": self.meta.animalid}, "trials"
        )
        try:
            return int(prev_trials["total_trial_no"].iloc[-1])
        except:
            return 0

    def remove_session_db(self):
        """ """
        pass
