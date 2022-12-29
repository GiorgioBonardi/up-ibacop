import os
import unified_planning as up
from unified_planning.model import ProblemKind
from unified_planning.engines.mixins import PortfolioSelectorMixin
from unified_planning.engines import Engine, Credits, OperationMode, Factory
from unified_planning.io.pddl_writer import PDDLWriter
from unified_planning.exceptions import UPException
from typing import Any, Dict, List, Optional, Tuple
from up_ibacop.utils.models import joinFile
import tempfile
import ast

credits = Credits('IBACOP',
                  'Isabel(?)',
                  '*@gmail.com',
                  'https://*/',
                  '?',
                  '?',
                  '?')

OPERATION_MODES_SUPPORTED = [
    OperationMode.ONESHOT_PLANNER
]

class Ibacop(PortfolioSelectorMixin, Engine):
    def __init__(self, model_path: Optional[str] = "model/RotationForest.model", dataset_path: Optional[str] = "model/global_features_simply.arff"):
        Engine.__init__(self)
        PortfolioSelectorMixin.__init__(self)

        self._model_path = model_path
        self._planner_list: List[str] = []
        self._parameters_list: List[Dict[str, Any]] = []

        try:
            self._init_planner_data(dataset_path)
        except:
            print("error")

    @property
    def name(self) -> str:
        return 'ibacop'

    @property
    def planner_list(self) -> List[str]:
        """Returns the list of engines in the portfolio."""
        return self._planner_list
    
    @property
    def parameters_list(self) -> List[str]:
        """Returns the list of parameters of the engines in the portfolio."""
        return self._parameters_list
    
    @staticmethod
    def supported_kind() -> ProblemKind:
        pass
        
    @staticmethod
    def supports(problem_kind: "ProblemKind") -> bool:
        # for name in Ibacop.planner_list():
        #     engine = Factory.engine(name)
        #     if not engine.supports(problem_kind):
        #         return False
        # return True
        return True

    @staticmethod
    def get_credits(**kwargs) -> Optional[Credits]:
        return credits

    @staticmethod
    def supports_operation_mode_for_selection(
        operation_mode: "up.engines.engine.OperationMode",
    ) -> bool:
        return operation_mode in OPERATION_MODES_SUPPORTED

    def _init_planner_data(self, dataset_path):
        word = "@attribute planner"
        with open(dataset_path, "r") as f:
            lines = f.readlines()
            for line in lines:
                if line.find(word) != -1:
                    line = line.replace(word, "")
                    line = line.replace("{", "")
                    line = line.replace("}", "")
                    line = line.replace(" ", "")
                    planner_list = []
                    parameters_dict_list = []
                    for tuple in line.strip().split(","):
                        tmp = tuple.split("|")
                        planner_name = tmp[0]
                        parameters_list = tmp[1]
                        #can't save the parameters list as {} because weka saves the list as {}
                        parameters_list = parameters_list.replace(";", ",")
                        parameters_list = "{" + parameters_list + "}"
                        parameters_dict = ast.literal_eval(parameters_list)                        

                        planner_list.append(planner_name)
                        parameters_dict_list.append(parameters_dict)
            self._planner_list = planner_list
            self._parameters_list = parameters_dict_list
            #better this or return the 2 lists

    def _get_best_engines(
        self,
        problem: "up.model.AbstractProblem",
        operation_mode: "up.engines.engine.OperationMode",
        max_engines: Optional[int] = None,
    ) -> Tuple[List[str], List[Dict[str, Any]]]:

        features = self._extract_features(problem)
        return self._get_prediction(features)
 
    def _extract_features(
        self,
        problem: "up.model.AbstractProblem"
    ) -> List[str]:

        current_path = os.path.dirname(__file__)
        current_wdir = os.getcwd()

        with tempfile.TemporaryDirectory() as tempdir:
            w = PDDLWriter(problem, True)
            domain_filename = os.path.join(tempdir, "domain.pddl")
            problem_filename = os.path.join(tempdir, "problem.pddl")
            w.write_domain(domain_filename)
            w.write_problem(problem_filename)

            # need to change the working dir for the following commands to work properly
            os.chdir(tempdir)
            print("\n***start extract features***\n")
            # features
            command = (
                "python2.7 "
                + current_path
                + "/utils/features/translate/translate.py "
                + domain_filename
                + " "
                + problem_filename
            )
            print(command)
            os.system(command)

            command = (
                current_path
                + "/utils/features/preprocess/preprocess < "
                + tempdir
                + "/output.sas"
            )
            os.system(command)

            command = (
                current_path
                + "/utils/features/ff-learner/roller3.0 -o "
                + domain_filename
                + " -f "
                + problem_filename
                + " -S 28"
            )
            os.system(command)

            command = (
                current_path
                + "/utils/features/heuristics/training.sh "
                + domain_filename
                + " "
                + problem_filename
            )
            os.system(command)

            command = (
                current_path
                + '/utils/search/downward --landmarks "lm=lm_merged([lm_hm(m=1),lm_rhw(),lm_zg()])" < '
                + tempdir
                + "/output"
            )
            os.system(command)

            command = (
                current_path
                + "/utils/search-mercury/downward ipc seq-agl-mercury <"
                + tempdir
                + "/output"
            )
            os.system(command)
            
            #formatting the list of names and the list of parameters into a list of tuples to be used by weka
            tuple_list = []
            planner_list = self.planner_list()
            parameter_list = self.parameters_list()
            for i in range(0,len(planner_list)):
                tmp_str = planner_list[i] + "|" + str(parameter_list[i])
                tmp_str = tmp_str.replace("{", "")
                tmp_str = tmp_str.replace("}", "")
                tmp_str = tmp_str.replace(",", ";")
                tuple_list.append(tuple)
            
            # join file
            temp_result = []
            for t in tuple_list:
                temp_result.append(t + ",?")

            joinFile.create_globals(tempdir, temp_result, tuple_list)

            print("\n***end extract features***\n")

            # go back to the previously working dir
            os.chdir(current_wdir)

            with open(os.path.join(tempdir, "global_features.arff")) as file_features:
                return file_features.readlines()

    def _get_prediction(
        self,
        features: List[str]
    ) -> List[str]:
        current_path = os.path.dirname(__file__)
        current_wdir = os.getcwd()

        with tempfile.TemporaryDirectory() as tempdir:

            features_path = os.path.join(tempdir, "global_features.arff")
            with open(features_path, "w") as file:
                for line in features:
                    # write each item on a new line
                    file.write("%s\n" % line)

            os.chdir(tempdir)

            # Call to `weka.jar` to remove unused `features`
            command = (
                "java -cp "
                + current_path
                + "/utils/models/weka.jar -Xms256m -Xmx1024m weka.filters.unsupervised.attribute.Remove -R 1-3,18,20,65,78-79,119-120 -i "
                + features_path
                + " -o "
                + tempdir
                + "/global_features_simply.arff"
            )
            os.system(command)
            # far predirre a weka
            # ottiene la lista dei pianificatori ordinata per probabilità di successo
            command = (
                "java -Xms256m -Xmx1024m -cp "
                + current_path
                + "/utils/models/weka.jar weka.classifiers.meta.RotationForest -l "
                + self._model_path
                + " -T "
                + tempdir
                + "/global_features_simply.arff -p 113 > "
                + tempdir
                + "/outputModel"
            )
            os.system(command)
            # The `model` creates the `list` of ALL planners relative to their probability of solving the `problem`
            command = (
                "python2.7 "
                + current_path
                + "/utils/models/parseWekaOutputFile.py "
                + tempdir
                + "/outputModel "
                + tempdir
                + "/listPlanner"
            )
            os.system(command)

            # go back to the previously working dir
            os.chdir(current_wdir)
            with open(os.path.join(tempdir, "listPlanner"), "r") as file:
                return file.readlines()

    def create_model(self, features) -> str:
        # per funzionare ha bisogno di:
        # weka all'interno della dir current_path/models/
        # e crea il .model in current_path (ovvero dove c'è il file ibacop.py)
        current_path = os.path.dirname(__file__)
        with tempfile.TemporaryDirectory() as tempdir:
            features_path = os.path.join(tempdir, "global_features.arff")

            with open(features_path, "w") as file:
                for line in features:
                    # write each item on a new line
                    file.write("%s\n" % line)

            # Call to `weka.jar` to remove unused `features`
            command = (
                "java -cp "
                + current_path
                + "/utils/models/weka.jar -Xms256m -Xmx1024m weka.filters.unsupervised.attribute.Remove -R 1-3,18,20,65,78-79,119-120 -i "
                + features_path
                + " -o "
                + tempdir
                + "/global_features_simply.arff"
            )
            os.system(command)

            # Save the model created
            command = (
                "java -Xms256m -Xmx1024m -cp "
                + current_path
                + "/utils/models/weka.jar weka.classifiers.meta.RotationForest  -t "
                + tempdir
                + "/global_features_simply.arff -d "
                + current_path
                + "/RotationForest.model"
            )
            os.system(command)

            model_path = os.path.join(current_path, "RotationForest.model")
            if os.path.isfile(model_path):
                return model_path
            else:
                return None