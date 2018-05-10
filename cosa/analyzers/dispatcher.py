# Copyright 2018 Cristian Mattarei
#
# Licensed under the modified BSD (3-clause BSD) License.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

from cosa.problem import VerificationType
from cosa.encoders.formulae import StringParser
from cosa.util.logger import Logger
from cosa.encoders.coreir import CoreIRParser
from cosa.analyzers.bmc import BMC, BMCConfig
from cosa.analyzers.bmc_liveness import BMCLiveness
from cosa.problem import VerificationStatus
from cosa.encoders.miter import Miter
from cosa.core.transition_system import HTS
from cosa.encoders.explicit_transition_system import ExplicitTSParser
from cosa.encoders.symbolic_transition_system import SymbolicTSParser


class ProblemSolver(object):
    parser = None
    
    def __init__(self):
        pass

    def solve_problem(self, problem, config):
        Logger.log("\n*** Analyzing problem %s ***"%(problem), 1)
        sparser = StringParser()

        bmc_config = self.problem2bmc_config(problem, config)
        bmc = BMC(problem.hts, bmc_config)
        bmc_liveness = BMCLiveness(problem.hts, bmc_config)
        res = VerificationStatus.UNK
        bmc_length = max(problem.bmc_length, config.bmc_length)
        bmc_length_min = max(problem.bmc_length_min, config.bmc_length_min)

        parsing_defs = [bmc_config.properties, bmc_config.lemmas, bmc_config.assumptions]
        for i in range(len(parsing_defs)):
            if parsing_defs[i] is not None:
                pdef_file = problem.relative_path+parsing_defs[i]
                if os.path.isfile(pdef_file):
                    with open(pdef_file) as f:
                        parsing_defs[i] = [p.strip() for p in f.read().strip().split("\n")]
                else:
                    parsing_defs[i] = [p.strip() for p in parsing_defs[i].split(",")]
            else:
                parsing_defs[i] = []

        [bmc_config.properties, bmc_config.lemmas, bmc_config.assumptions] = parsing_defs

        assumps = None
        lemmas = None
        
        if problem.verification != VerificationType.EQUIVALENCE:
            assumps = [t[1] for t in sparser.parse_formulae(bmc_config.assumptions)]
            lemmas = [t[1] for t in sparser.parse_formulae(bmc_config.lemmas)]
            problem.hts.assumptions = assumps

        if problem.verification == VerificationType.SAFETY:
            count = 0
            list_status = []
            (strprop, prop, types) = sparser.parse_formulae(bmc_config.properties)[0]
            res, trace, _ = bmc.safety(prop, bmc_length, bmc_length_min, lemmas)
            problem.status = res
            problem.trace = trace

        if problem.verification == VerificationType.LIVENESS:
            count = 0
            list_status = []
            (strprop, prop, types) = sparser.parse_formulae(bmc_config.properties)[0]
            res, trace = bmc_liveness.liveness(prop, bmc_length, bmc_length_min, lemmas)
            problem.status = res
            problem.trace = trace

        if problem.verification == VerificationType.EVENTUALLY:
            count = 0
            list_status = []
            (strprop, prop, types) = sparser.parse_formulae(bmc_config.properties)[0]
            res, trace = bmc_liveness.eventually(prop, bmc_length, bmc_length_min, lemmas)
            problem.status = res
            problem.trace = trace
            
        if problem.verification == VerificationType.EQUIVALENCE:
            if problem.equivalence:
                problem.hts2 = self.parse_model(problem.relative_path, problem.equivalence, config.abstract_clock, "System 2")

            htseq, miter_out = Miter.combine_systems(problem.hts, problem.hts2, problem.bmc_length, problem.symbolic_init, True)

            if bmc_config.assumptions is not None:
                assumps = [t[1] for t in sparser.parse_formulae(bmc_config.assumptions)]

            if bmc_config.lemmas is not None:
                lemmas = [t[1] for t in sparser.parse_formulae(bmc_config.lemmas)]
            
            htseq.assumptions = assumps
            bmcseq = BMC(htseq, bmc_config)
            res, trace, t = bmcseq.safety(miter_out, problem.bmc_length, problem.bmc_length_min, lemmas)
            problem.status = res
            problem.trace = trace

        if problem.assumptions is not None:
            problem.hts.assumptions = None
            
        Logger.log("\n*** Result for problem %s is %s ***"%(problem, res), 1)

    def parse_model(self, relative_path, model_files, abstract_clock=False, name=None):
        hts = HTS("Top level")

        models = model_files.split(",")
        
        for strfile in models:
            filetype = strfile.split(".")[-1]
            strfile = relative_path+strfile
            parser = None

            if filetype == CoreIRParser.get_extension():
                parser = CoreIRParser(abstract_clock)
                parser.boolean = False
                self.parser = parser

            if filetype == ExplicitTSParser.get_extension():
                parser = ExplicitTSParser()

            if filetype == SymbolicTSParser.get_extension():
                parser = SymbolicTSParser()

            if parser is not None:
                Logger.msg("Parsing file \"%s\"... "%(strfile), 0)
                hts_a = parser.parse_file(strfile)
                hts.combine(hts_a)

                Logger.log("DONE", 0)
                continue

            Logger.error("Filetype \"%s\" unsupported"%filetype)
            
        if Logger.level(1):
            print(hts.print_statistics(name))

        return hts
        
    def solve_problems(self, problems, config):
        hts = None
        hts2 = None
        hts = self.parse_model(problems.relative_path, problems.model_file, problems.abstract_clock, "System 1")
        
        if problems.equivalence is not None:
            hts2 = self.parse_model(problems.relative_path, problems.equivalence, problems.abstract_clock, "System 2")
        
        for problem in problems.problems:
            problem.hts = hts
            problem.hts2 = hts2
            problem.relative_path = problems.relative_path
            self.solve_problem(problem, config)

    def problem2bmc_config(self, problem, config):
        bmc_config = BMCConfig()
        
        bmc_config.smt2file = problem.smt2_tracing if problem.smt2_tracing is not None else config.smt2file
        bmc_config.full_trace = problem.full_trace or config.full_trace
        bmc_config.prefix = problem.name
        bmc_config.strategy = BMCConfig.get_strategies()[0][0]
        bmc_config.skip_solving = problem.skip_solving
        bmc_config.map_function = self.parser.remap_an2or
        bmc_config.solver_name = config.solver_name if problem.solver_name is None else problem.solver_name
        bmc_config.vcd_trace = problem.vcd or config.vcd
        bmc_config.prove = problem.prove
        bmc_config.properties = problem.formula
        bmc_config.assumptions = problem.assumptions
        bmc_config.lemmas = problem.lemmas

        return bmc_config
