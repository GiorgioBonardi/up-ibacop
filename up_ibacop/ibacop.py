import os
import unified_planning as up
from unified_planning.environment import Environment
from unified_planning.model import ProblemKind
from unified_planning.engines.mixins import PortfolioSelectorMixin
from unified_planning.engines import Engine, Credits, Factory
from unified_planning.io.pddl_writer import PDDLWriter
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

rootpath = os.path.dirname(__file__)
default_model_path = os.path.join(rootpath, "model/RotationForest.model")
default_dataset_path = os.path.join(rootpath, "model/global_features_simply.arff")

def extract_tuple_from_list(
        tuple_list: List[str]
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """This method takes a list of tuples in string format and returns them with the right format"""
        planners = []
        parameters= []
        for tuple in tuple_list:
            tmp = tuple.split("|")
            planner_name = tmp[0]
            planner_parameters = tmp[1]
            # Can't save the parameters list with {} because their represent a special character for weka
            planner_parameters = planner_parameters.replace(";", ",")
            planner_parameters = "{" + planner_parameters + "}"
            planner_parameters_dict = ast.literal_eval(planner_parameters)                        

            planners.append(planner_name)
            parameters.append(planner_parameters_dict)
        return planners, parameters

def init_planners_data() -> Tuple[List[str], List[Dict[str, Any]]]:
        word = "@attribute planner"
        with open(default_dataset_path, "r") as f:
            lines = f.readlines()
            for line in lines:
                if line.find(word) != -1:
                    line = line.replace(word, "")
                    line = line.replace("{", "")
                    line = line.replace("}", "")
                    line = line.replace(" ", "")
                    planners, parameters = extract_tuple_from_list(line.strip().split(","))

            return planners, parameters

default_planners, default_parameters = init_planners_data()

class Ibacop(PortfolioSelectorMixin, Engine):
    def __init__(self):
        Engine.__init__(self)
        PortfolioSelectorMixin.__init__(self)

    @property
    def name(self) -> str:
        return 'ibacop'

    @staticmethod
    def supported_kind() -> ProblemKind:
        pass
        
    @staticmethod
    def supports(problem_kind: "ProblemKind") -> bool:
        for planner in default_planners:
            factory = Factory(Environment())
            engine = factory.engine(planner)
            if engine.supports(problem_kind):
                return True
        return False

    @staticmethod
    def get_credits(**kwargs) -> Optional[Credits]:
        return credits

    @staticmethod
    def satisfies(
        optimality_guarantee: "up.engines.mixins.oneshot_planner.OptimalityGuarantee",
    ) -> bool:
        for planner in default_planners:
            factory = Factory(Environment())
            engine = factory.engine(planner)
            if not engine.satisfies(optimality_guarantee):
                return False
        return True

    def _get_best_oneshot_planners(
        self,
        problem: "up.model.AbstractProblem",
        max_planners: Optional[int] = None,
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
    
        features = self._extract_features(problem)
        model_prediction_list = self._get_prediction(features)

        n_selected_planners = 0
        list_planners = []
        for planner in model_prediction_list:
            planner = planner.strip()
            list_planners.append(planner)
            n_selected_planners += 1
            if n_selected_planners == max_planners:
                break

        return extract_tuple_from_list(list_planners)

    def _extract_features(
        self,
        problem: "up.model.AbstractProblem"
    ) -> List[str]:
        """This method extracts the features of the 'problem' in input and returns them as a List[str]"""
        current_path = os.path.dirname(__file__)
        current_wdir = os.getcwd()

        with tempfile.TemporaryDirectory() as tempdir:
            w = PDDLWriter(problem, True)
            domain_filename = os.path.join(tempdir, "domain.pddl")
            problem_filename = os.path.join(tempdir, "problem.pddl")
            w.write_domain(domain_filename)
            w.write_problem(problem_filename)

            # Need to change the working dir for the following commands to work properly
            os.chdir(tempdir)

            print("\n***start extract features***\n")
            command = (
                "python2.7 "
                + current_path
                + "/utils/features/translate/translate.py "
                + domain_filename
                + " "
                + problem_filename
            )
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
            
            # Formatting the list of names and the list of parameters into a list of tuples to be used by weka
            tuple_list = []
            for i in range(0,len(default_planners)):
                tmp_str = default_planners[i] + "|" + str(default_parameters[i])
                tmp_str = tmp_str.replace("{", "")
                tmp_str = tmp_str.replace("}", "")
                tmp_str = tmp_str.replace(",", ";")
                tuple_list.append(tmp_str)
            
            temp_result = []
            for t in tuple_list:
                temp_result.append(str(t) + ",?")

            joinFile.create_globals(tempdir, temp_result, tuple_list)

            print("\n***end extract features***\n")

            # Return to the previous working dir
            os.chdir(current_wdir)

            with open(os.path.join(tempdir, "global_features.arff")) as file_features:
                return file_features.readlines()

    def _get_prediction(
        self,
        features: List[str]
    ) -> List[str]:
        """This method takes the features and returns a sorted list of planners created by weka using a trained model"""
        current_path = os.path.dirname(__file__)
        current_wdir = os.getcwd()

        with tempfile.TemporaryDirectory() as tempdir:

            features_path = os.path.join(tempdir, "global_features.arff")
            with open(features_path, "w") as file:
                for line in features:
                    file.write("%s\n" % line)

            # Need to change the working dir for the following commands to work properly
            os.chdir(tempdir)

            # Call to 'weka.jar' to remove unused 'features'
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

            # Weka returns the predictions
            command = (
                "java -Xms256m -Xmx1024m -cp "
                + current_path
                + "/utils/models/weka.jar weka.classifiers.meta.RotationForest -l "
                + default_model_path
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

            # Return to the previous working dir
            os.chdir(current_wdir)

            with open(os.path.join(tempdir, "listPlanner"), "r") as file:
                return file.readlines()