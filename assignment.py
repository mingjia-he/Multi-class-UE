import heapq
import math
import time

import networkx as nx
import scipy

from network_import import *
from utils import PathUtils
from scipy.optimize import minimize,root,fsolve
vot1=1
vot2=10
price1=0.1
price2=0.1
class FlowTransportNetwork:

    def __init__(self):
        self.linkSet = {}
        self.nodeSet = {}

        self.tripSet = {}
        self.zoneSet = {}
        self.originZones = {}

        self.networkx_graph = None

    def to_networkx(self):
        if self.networkx_graph is None:
            self.networkx_graph = nx.DiGraph([(int(begin),int(end)) for (begin,end) in self.linkSet.keys()])
        return self.networkx_graph

    def reset_flow(self):
        for link in self.linkSet.values():
            link.reset_flow()

    def reset(self):
        for link in self.linkSet.values():
            link.reset()


class Zone:
    def __init__(self, zoneId: str):
        self.zoneId = zoneId

        self.lat = 0
        self.lon = 0
        self.destList = []  # list of zone ids (strs)


class Node:
    """
    This class has attributes associated with any node
    """

    def __init__(self, nodeId: str):
        self.Id = nodeId

        self.lat = 0
        self.lon = 0

        self.outLinks = []  # list of node ids (strs)
        self.inLinks = []  # list of node ids (strs)

        # For Dijkstra
        self.label = np.inf
        self.pred = None


class Link:
    """
    This class has attributes associated with any link
    """

    def __init__(self,
                 init_node: str,
                 term_node: str,
                 capacity: float,
                 length: float,
                 fft: float,
                 b: float,
                 power: float,
                 speed_limit: float,
                 toll: float,
                 linkType
                 ):
        self.init_node = init_node
        self.term_node = term_node
        self.max_capacity = float(capacity)  # veh per hour
        self.length = float(length)  # Length
        self.fft = float(fft)  # Free flow travel time (min)
        self.beta = float(power)
        self.alpha = float(b)
        self.speedLimit = float(speed_limit)
        self.toll = float(toll)
        self.linkType = linkType

        self.curr_capacity_percentage = 1
        self.capacity = self.max_capacity
        self.flow = 0.0
        self.flow1 = 0.0
        self.flow2 = 0.0
        self.cost1 = self.fft
        self.cost2 = self.fft

    # Method not used for assignment
    def modify_capacity(self, delta_percentage: float):
        assert -1 <= delta_percentage <= 1
        self.curr_capacity_percentage += delta_percentage
        self.curr_capacity_percentage = max(0, min(1, self.curr_capacity_percentage))
        self.capacity = self.max_capacity * self.curr_capacity_percentage

    def reset(self):
        self.curr_capacity_percentage = 1
        self.capacity = self.max_capacity
        self.reset_flow()

    def reset_flow(self):
        self.flow1 = 0.0
        self.flow2 = 0.0
        self.flow = 0.0
        self.cost1 = self.fft
        self.cost2 = self.fft


class Demand:
    def __init__(self,
                 init_node: str,
                 term_node: str,
                 demand: float
                 ):
        self.fromZone = init_node
        self.toNode = term_node
        self.demand = float(demand)


def DijkstraHeap(origin, network: FlowTransportNetwork, user_class):
    """
    Calcualtes shortest path from an origin to all other destinations.
    The labels and preds are stored in node instances.
    """
    if user_class==1:
        for n in network.nodeSet:
            network.nodeSet[n].label = np.inf
            network.nodeSet[n].pred = None
        network.nodeSet[origin].label = 0.0
        network.nodeSet[origin].pred = None
        SE = [(0, origin)]
        while SE:
            currentNode = heapq.heappop(SE)[1]
            currentLabel = network.nodeSet[currentNode].label
            for toNode in network.nodeSet[currentNode].outLinks:
                link = (currentNode, toNode)
                newNode = toNode
                newPred = currentNode
                existingLabel = network.nodeSet[newNode].label
                newLabel = currentLabel + network.linkSet[link].cost1
                if newLabel < existingLabel:
                    heapq.heappush(SE, (newLabel, newNode))
                    network.nodeSet[newNode].label = newLabel
                    network.nodeSet[newNode].pred = newPred
    else: 
        for n in network.nodeSet:
            network.nodeSet[n].label = np.inf
            network.nodeSet[n].pred = None
        network.nodeSet[origin].label = 0.0
        network.nodeSet[origin].pred = None
        SE = [(0, origin)]
        while SE:
            currentNode = heapq.heappop(SE)[1]
            currentLabel = network.nodeSet[currentNode].label
            for toNode in network.nodeSet[currentNode].outLinks:
                link = (currentNode, toNode)
                newNode = toNode
                newPred = currentNode
                existingLabel = network.nodeSet[newNode].label
                newLabel = currentLabel + network.linkSet[link].cost2
                if newLabel < existingLabel:
                    heapq.heappush(SE, (newLabel, newNode))
                    network.nodeSet[newNode].label = newLabel
                    network.nodeSet[newNode].pred = newPred


def BPRcostFunction(optimal: bool,
                    fft: float,
                    alpha: float,
                    flow: float,
                    capacity: float,
                    beta: float,
                    length: float,
                    maxSpeed: float
                    ) -> float:
    if capacity < 1e-3:
        return np.finfo(np.float32).max
    if optimal:
        return fft * (1 + (alpha * math.pow((flow * 1.0 / capacity), beta)) * (beta + 1))
    return fft * (1 + alpha * math.pow((flow * 1.0 / capacity), beta))


def constantCostFunction(optimal: bool,
                         fft: float,
                         alpha: float,
                         flow: float,
                         capacity: float,
                         beta: float,
                         length: float,
                         maxSpeed: float
                         ) -> float:
    if optimal:
        return fft + flow
    return fft


def greenshieldsCostFunction(optimal: bool,
                             fft: float,
                             alpha: float,
                             flow: float,
                             capacity: float,
                             beta: float,
                             length: float,
                             maxSpeed: float
                             ) -> float:
    if capacity < 1e-3:
        return np.finfo(np.float32).max
    if optimal:
        return (length * (capacity ** 2)) / (maxSpeed * (capacity - flow) ** 2)
    return length / (maxSpeed * (1 - (flow / capacity)))


def updateTravelTime(network: FlowTransportNetwork, optimal: bool = False, costFunction=BPRcostFunction):
    """
    This method updates the travel time on the links with the current flow
    """
    for l in network.linkSet:
        network.linkSet[l].cost1 = vot1*costFunction(optimal,
                                               network.linkSet[l].fft,
                                               network.linkSet[l].alpha,
                                               network.linkSet[l].flow,
                                               network.linkSet[l].capacity,
                                               network.linkSet[l].beta,
                                               network.linkSet[l].length,
                                               network.linkSet[l].speedLimit
                                               )+price1*network.linkSet[l].length
        network.linkSet[l].cost2 = vot2*costFunction(optimal,
                                               network.linkSet[l].fft,
                                               network.linkSet[l].alpha,
                                               network.linkSet[l].flow,
                                               network.linkSet[l].capacity,
                                               network.linkSet[l].beta,
                                               network.linkSet[l].length,
                                               network.linkSet[l].speedLimit
                                               )+price2*network.linkSet[l].length


# def findAlpha_2(x_bar, network: FlowTransportNetwork, optimal: bool = False, costFunction=BPRcostFunction):

#     """
#     This uses unconstrained optimization to calculate the optimal step size required
#     for Frank-Wolfe Algorithm
#     """

#     def df(alpha):
#         # assert 0 <= alpha1 <= 1
#         # assert 0 <= alpha2 <= 1
#         # assert 0 <= alpha <= 1
#         sum_derivative = 0  # this line is the derivative of the objective function.
#         for l in network.linkSet:
#             tmpFlow1 = alpha1 * (x_bar[0][l]) + (1 - alpha1) * network.linkSet[l].flow1
#             tmpFlow2 = alpha2 * (x_bar[1][l]) + (1 - alpha2) * network.linkSet[l].flow2
#             tmpFlow=tmpFlow1+tmpFlow2

#             tmpCost = costFunction(optimal,
#                                    network.linkSet[l].fft,
#                                    network.linkSet[l].alpha,
#                                    tmpFlow,
#                                    network.linkSet[l].capacity,
#                                    network.linkSet[l].beta,
#                                    network.linkSet[l].length,
#                                    network.linkSet[l].speedLimit
#                                    )
#             tmpCost_c1=tmpCost*vot1+price1*network.linkSet[l].length
#             tmpCost_c2=tmpCost*vot2+price2*network.linkSet[l].length

#             #sum_derivative = sum_derivative + (x_bar[l] - network.linkSet[l].flow) * tmpCost
#             sum_derivative = sum_derivative + (x_bar[0][l]-network.linkSet[l].flow1) * tmpCost_c1 + (x_bar[1][l]-network.linkSet[l].flow2) * tmpCost_c2

#         return sum_derivative

#     # sol = scipy.optimize.root_scalar(df, x0=np.array([0.5,0.5]), bracket=(0, 1))
#     # assert 0 <= sol.root <= 1
#     # return sol.root
#     bounds = [(0, 1), (0, 1)]
#     initial_guess = [0.5, 0.5]
#     solution = minimize(df, initial_guess, method='Nelder-Mead', bounds=bounds)
#     alpha1,alpha2 = solution.x
#     if alpha1>1:
#         alpha1=1
#     if alpha2>1:
#         alpha2=1
#     return [alpha1,alpha2]

def findAlpha(x_bar, network: FlowTransportNetwork, optimal: bool = False, costFunction=BPRcostFunction):

    """
    This uses unconstrained optimization to calculate the optimal step size required
    for Frank-Wolfe Algorithm
    """

    def df(alpha):
        assert 0 <= alpha <= 1
        sum_derivative = 0  # this line is the derivative of the objective function.
        for l in network.linkSet:
            tmpFlow1 = alpha * (x_bar[0][l]) + (1 - alpha) * network.linkSet[l].flow1
            tmpFlow2 = alpha * (x_bar[1][l]) + (1 - alpha) * network.linkSet[l].flow2
            tmpFlow=tmpFlow1+tmpFlow2

            tmpCost = costFunction(optimal,
                                   network.linkSet[l].fft,
                                   network.linkSet[l].alpha,
                                   tmpFlow,
                                   network.linkSet[l].capacity,
                                   network.linkSet[l].beta,
                                   network.linkSet[l].length,
                                   network.linkSet[l].speedLimit
                                   )
            tmpCost_c1=tmpCost*vot1+price1*network.linkSet[l].length
            tmpCost_c2=tmpCost*vot2+price2*network.linkSet[l].length

            #sum_derivative = sum_derivative + (x_bar[l] - network.linkSet[l].flow) * tmpCost
            sum_derivative = sum_derivative + (x_bar[0][l]-network.linkSet[l].flow1) * tmpCost_c1 + (x_bar[1][l]-network.linkSet[l].flow2) * tmpCost_c2

        return sum_derivative

    sol = scipy.optimize.root_scalar(df, x0=np.array([0.5]), bracket=(0, 1))
    assert 0 <= sol.root <= 1
    return sol.root



def tracePreds(dest, network: FlowTransportNetwork):
    """
    This method traverses predecessor nodes in order to create a shortest path
    """
    prevNode = network.nodeSet[dest].pred
    spLinks = []
    while prevNode is not None:
        spLinks.append((prevNode, dest))
        dest = prevNode
        prevNode = network.nodeSet[dest].pred
    return spLinks


def loadAON(network: FlowTransportNetwork, computeXbar: bool = True):
    """
    This method produces auxiliary flows for all or nothing loading.
    """
    x_bar1 = {l: 0.0 for l in network.linkSet}
    x_bar2 = {l: 0.0 for l in network.linkSet}
    SPTT = 0.0
    for r in network.originZones:
        DijkstraHeap(r, network=network,user_class=1)
        for s in network.zoneSet[r].destList:
            dem1 = network.tripSet[r, s].demand

            if dem1 <= 0:
                continue

            SPTT = SPTT + network.nodeSet[s].label * dem1

            if computeXbar and r != s:
                for spLink in tracePreds(s, network):
                    x_bar1[spLink] = x_bar1[spLink] + dem1

    for r in network.originZones:
        DijkstraHeap(r, network=network,user_class=2)
        for s in network.zoneSet[r].destList:
            dem2 = network.tripSet[r, s].demand

            if dem2 <= 0:
                continue

            SPTT = SPTT + network.nodeSet[s].label * dem2

            if computeXbar and r != s:
                for spLink in tracePreds(s, network):
                    x_bar2[spLink] = x_bar2[spLink] + dem2


    x_bar=[x_bar1,x_bar2]

    return SPTT, x_bar


def readDemand(demand_df: pd.DataFrame, network: FlowTransportNetwork):
    for index, row in demand_df.iterrows():

        init_node = str(int(row["init_node"]))
        term_node = str(int(row["term_node"]))
        demand = row["demand"]

        network.tripSet[init_node, term_node] = Demand(init_node, term_node, demand)
        if init_node not in network.zoneSet:
            network.zoneSet[init_node] = Zone(init_node)
        if term_node not in network.zoneSet:
            network.zoneSet[term_node] = Zone(term_node)
        if term_node not in network.zoneSet[init_node].destList:
            network.zoneSet[init_node].destList.append(term_node)

    print(len(network.tripSet), "OD pairs")
    print(len(network.zoneSet), "OD zones")


def readNetwork(network_df: pd.DataFrame, network: FlowTransportNetwork):
    for index, row in network_df.iterrows():

        init_node = str(int(row["init_node"]))
        term_node = str(int(row["term_node"]))
        capacity = row["capacity"]
        length = row["length"]
        free_flow_time = row["free_flow_time"]
        b = row["b"]
        power = row["power"]
        speed = row["speed"]
        toll = row["toll"]
        link_type = row["link_type"]

        network.linkSet[init_node, term_node] = Link(init_node=init_node,
                                                     term_node=term_node,
                                                     capacity=capacity,
                                                     length=length,
                                                     fft=free_flow_time,
                                                     b=b,
                                                     power=power,
                                                     speed_limit=speed,
                                                     toll=toll,
                                                     linkType=link_type
                                                     )
        if init_node not in network.nodeSet:
            network.nodeSet[init_node] = Node(init_node)
        if term_node not in network.nodeSet:
            network.nodeSet[term_node] = Node(term_node)
        if term_node not in network.nodeSet[init_node].outLinks:
            network.nodeSet[init_node].outLinks.append(term_node)
        if init_node not in network.nodeSet[term_node].inLinks:
            network.nodeSet[term_node].inLinks.append(init_node)

    print(len(network.nodeSet), "nodes")
    print(len(network.linkSet), "links")


def get_TSTT(network: FlowTransportNetwork, costFunction=BPRcostFunction, use_max_capacity: bool = True):
    TSTT = round(sum([network.linkSet[l].flow1  * vot1 * costFunction(optimal=False,
                                                             fft=network.linkSet[
                                                                 l].fft,
                                                             alpha=network.linkSet[
                                                                 l].alpha,
                                                             flow=network.linkSet[
                                                                 l].flow,
                                                             capacity=network.linkSet[
                                                                 l].max_capacity if use_max_capacity else network.linkSet[
                                                                 l].capacity,
                                                             beta=network.linkSet[
                                                                 l].beta,
                                                             length=network.linkSet[
                                                                 l].length,
                                                             maxSpeed=network.linkSet[
                                                                 l].speedLimit
                                                             ) for l in
                      network.linkSet])
                      +sum([network.linkSet[l].flow2  * vot2 * costFunction(optimal=False,
                                                               fft=network.linkSet[
                                                                 l].fft,
                                                             alpha=network.linkSet[
                                                                 l].alpha,
                                                             flow=network.linkSet[
                                                                 l].flow,
                                                             capacity=network.linkSet[
                                                                 l].max_capacity if use_max_capacity else network.linkSet[
                                                                 l].capacity,
                                                             beta=network.linkSet[
                                                                 l].beta,
                                                             length=network.linkSet[
                                                                 l].length,
                                                             maxSpeed=network.linkSet[
                                                                 l].speedLimit
                                                             ) for l in
                      network.linkSet]), 2)
    return TSTT


def assignment_loop(network: FlowTransportNetwork,
                    algorithm: str = "FW",
                    systemOptimal: bool = False,
                    costFunction=BPRcostFunction,
                    accuracy: float = 0.001,
                    maxIter: int = 1000,
                    maxTime: int = 60,
                    verbose: bool = True):
    """
    For explaination of the algorithm see Chapter 7 of:
    https://sboyles.github.io/blubook.html
    PDF:
    https://sboyles.github.io/teaching/ce392c/book.pdf
    """
    network.reset_flow()

    iteration_number = 1
    gap = np.inf
    TSTT = np.inf
    assignmentStartTime = time.time()

    # Check if desired accuracy is reached
    while gap > accuracy:

        # Get x_bar throug all-or-nothing assignment
        _, x_bar = loadAON(network=network)

        if algorithm == "MSA" or iteration_number == 1:
            alpha = (1 / iteration_number)
        elif algorithm == "FW":
            # If using Frank-Wolfe determine the step size alpha by solving a nonlinear equation
            alpha = findAlpha(x_bar,
                              network=network,
                              optimal=systemOptimal,
                              costFunction=costFunction)
        else:
            print("Terminating the program.....")
            print("The solution algorithm ", algorithm, " does not exist!")
            raise TypeError('Algorithm must be MSA or FW')

        # Apply flow improvement
        for l in network.linkSet:
            network.linkSet[l].flow1 = alpha * x_bar[0][l] + (1 - alpha) * network.linkSet[l].flow1
            network.linkSet[l].flow2 = alpha * x_bar[1][l] + (1 - alpha) * network.linkSet[l].flow2
            network.linkSet[l].flow = network.linkSet[l].flow1+network.linkSet[l].flow2

        # Compute the new travel time
        updateTravelTime(network=network,
                         optimal=systemOptimal,
                         costFunction=costFunction)

        # Compute the relative gap
        SPTT, _ = loadAON(network=network, computeXbar=False)
        SPTT = round(SPTT, 9)
        TSTT = round(sum([network.linkSet[l].flow1 * network.linkSet[l].cost1+
                          network.linkSet[l].flow2 * network.linkSet[l].cost2 for l in
                          network.linkSet]), 9)

        # print(TSTT, SPTT, "TSTT, SPTT, Max capacity", max([l.capacity for l in network.linkSet.values()]))
        gap = (TSTT / SPTT) - 1
        if gap < 0:
            print("Error, gap is less than 0, this should not happen")
            print("TSTT", "SPTT", TSTT, SPTT)

            # Uncomment for debug

            # print("Capacities:", [l.capacity for l in network.linkSet.values()])
            # print("Flows:", [l.flow for l in network.linkSet.values()])

        # Compute the real total travel time (which in the case of system optimal rounting is different from the TSTT above)
        TSTT = get_TSTT(network=network, costFunction=costFunction)

        iteration_number += 1
        if iteration_number > maxIter:
            if verbose:
                print(
                    "The assignment did not converge to the desired gap and the max number of iterations has been reached")
                print("Assignment took", round(time.time() - assignmentStartTime, 5), "seconds")
                print("Current gap:", round(gap, 5))
            return TSTT
        if time.time() - assignmentStartTime > maxTime:
            if verbose:
                print("The assignment did not converge to the desired gap and the max time limit has been reached")
                print("Assignment did ", iteration_number, "iterations")
                print("Current gap:", round(gap, 5))
            return TSTT

    if verbose:
        print("Assignment converged in ", iteration_number, "iterations")
        print("Assignment took", round(time.time() - assignmentStartTime, 5), "seconds")
        print("Current gap:", round(gap, 5))

    return TSTT


def writeResults(network: FlowTransportNetwork, output_file: str, costFunction=BPRcostFunction,
                 systemOptimal: bool = False, verbose: bool = True):
    outFile = open(output_file, "w")
    TSTT = get_TSTT(network=network, costFunction=costFunction)
    if verbose:
        print("\nTotal system travel time:", f'{TSTT} secs')
    tmpOut = "Total Travel Time:\t" + str(TSTT)
    outFile.write(tmpOut + "\n")
    tmpOut = "Cost function used:\t" + BPRcostFunction.__name__
    outFile.write(tmpOut + "\n")
    tmpOut = ["User equilibrium (UE) or system optimal (SO):\t"] + ["SO" if systemOptimal else "UE"]
    outFile.write("".join(tmpOut) + "\n\n")
    tmpOut = "init_node\tterm_node\tflow1\tflow2\ttravelTime"
    outFile.write(tmpOut + "\n")
    for i in network.linkSet:
        tmpOut = str(network.linkSet[i].init_node) + "\t" + str(
            network.linkSet[i].term_node) + "\t" + str(
            int(network.linkSet[i].flow1)) + "\t"+ str(
            int(network.linkSet[i].flow2)) + "\t"  + str(costFunction(False,
                                                               network.linkSet[i].fft,
                                                               network.linkSet[i].alpha,
                                                               network.linkSet[i].flow,
                                                               network.linkSet[i].max_capacity,
                                                               network.linkSet[i].beta,
                                                               network.linkSet[i].length,
                                                               network.linkSet[i].speedLimit
                                                               ))
        outFile.write(tmpOut + "\n")
    outFile.close()


def load_network(net_file: str,
                 demand_file: str = None,
                 force_net_reprocess: bool = False,
                 verbose: bool = True
                 ) -> FlowTransportNetwork:
    readStart = time.time()

    if demand_file is None:
        demand_file = '_'.join(net_file.split("_")[:-1] + ["trips.tntp"])

    net_name = net_file.split("/")[-1].split("_")[0]

    if verbose:
        print(f"Loading network {net_name}...")

    net_df, demand_df = import_network(
        net_file,
        demand_file,
        force_reprocess=force_net_reprocess
    )

    network = FlowTransportNetwork()

    readDemand(demand_df, network=network)
    readNetwork(net_df, network=network)

    network.originZones = set([k[0] for k in network.tripSet])

    if verbose:
        print("Network", net_name, "loaded")
        print("Reading the network data took", round(time.time() - readStart, 2), "secs\n")

    return network


def computeAssingment(net_file: str,
                      demand_file: str = None,
                      algorithm: str = "FW",  # FW or MSA
                      costFunction=BPRcostFunction,
                      systemOptimal: bool = False,
                      accuracy: float = 0.0001,
                      maxIter: int = 1000,
                      maxTime: int = 60,
                      results_file: str = None,
                      force_net_reprocess: bool = False,
                      verbose: bool = True
                      ) -> float:
    """
    This is the main function to compute the user equilibrium UE (default) or system optimal (SO) traffic assignment
    All the networks present on https://github.com/bstabler/TransportationNetworks following the tntp format can be loaded


    :param net_file: Name of the network (net) file following the tntp format (see https://github.com/bstabler/TransportationNetworks)
    :param demand_file: Name of the demand (trips) file following the tntp format (see https://github.com/bstabler/TransportationNetworks), leave None to use dafault demand file
    :param algorithm:
           - "FW": Frank-Wolfe algorithm (see https://en.wikipedia.org/wiki/Frank%E2%80%93Wolfe_algorithm)
           - "MSA": Method of successive averages
           For more information on how the algorithms work see https://sboyles.github.io/teaching/ce392c/book.pdf
    :param costFunction: Which cost function to use to compute travel time on edges, currently available functions are:
           - BPRcostFunction (see https://rdrr.io/rforge/travelr/man/bpr.function.html)
           - greenshieldsCostFunction (see Greenshields, B. D., et al. "A study of traffic capacity." Highway research board proceedings. Vol. 1935. National Research Council (USA), Highway Research Board, 1935.)
           - constantCostFunction
    :param systemOptimal: Wheather to compute the system optimal flows instead of the user equilibrium
    :param accuracy: Desired assignment precision gap
    :param maxIter: Maximum nuber of algorithm iterations
    :param maxTime: Maximum seconds allowed for the assignment
    :param results_file: Name of the desired file to write the results,
           by default the result file is saved with the same name as the input network with the suffix "_flow.tntp" in the same folder
    :param force_net_reprocess: True if the network files should be reprocessed from the tntp sources
    :param verbose: print useful info in standard output
    :return: Totoal system travel time
    """

    network = load_network(net_file=net_file, demand_file=demand_file, verbose=verbose, force_net_reprocess=force_net_reprocess)

    if verbose:
        print("Computing assignment...")
    TSTT = assignment_loop(network=network, algorithm=algorithm, systemOptimal=systemOptimal, costFunction=costFunction,
                           accuracy=accuracy, maxIter=maxIter, maxTime=maxTime, verbose=verbose)

    if results_file is None:
        results_file = '_'.join(net_file.split("_")[:-1] + ["flow.tntp"])

    writeResults(network=network,
                 output_file=results_file,
                 costFunction=costFunction,
                 systemOptimal=systemOptimal,
                 verbose=verbose)

    return TSTT


if __name__ == '__main__':

    # This is an example usage for calculating System Optimal and User Equilibrium with Frank-Wolfe

    net_file = str(PathUtils.sioux_falls_net_file)

    total_system_travel_time_optimal = computeAssingment(net_file=net_file,
                                                         algorithm="FW",
                                                         costFunction=BPRcostFunction,
                                                         systemOptimal=True,
                                                         verbose=True,
                                                         accuracy=0.00001,
                                                         maxIter=1000,
                                                         maxTime=6000000)

    total_system_travel_time_equilibrium = computeAssingment(net_file=net_file,
                                                             algorithm="FW",
                                                             costFunction=BPRcostFunction,
                                                             systemOptimal=False,
                                                             verbose=True,
                                                             accuracy=0.001,
                                                             maxIter=1000,
                                                             maxTime=6000000)

    print("UE - SO = ", total_system_travel_time_equilibrium - total_system_travel_time_optimal)
