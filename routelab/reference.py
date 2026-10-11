"""Conservative integer scaling can restrict the original feasible set.

Original floating-point matrices are always used to validate and score returned routes.
"""

import math

from .solvers import SearchStopped


def ortools_solve(search):
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError as exc:
        raise ValueError(
            "Install requirements-reference.txt to enable the local OR-Tools reference"
        ) from exc
    scenario, matrix = search.scenario, search.matrix
    scale = 1000
    depot = matrix.index[scenario.depot_id]
    manager = pywrapcp.RoutingIndexManager(len(matrix.ids), scenario.fleet.count, depot)
    routing = pywrapcp.RoutingModel(manager)
    maximum = max((v for row in matrix.distances for v in row if v is not None), default=1)
    unreachable = int((maximum + 1) * (len(matrix.ids) + scenario.fleet.count) * scale * 10)

    def distance(a, b):
        value = matrix.distances[manager.IndexToNode(a)][manager.IndexToNode(b)]
        return unreachable if value is None else math.ceil(value * scale)

    def duration(a, b):
        i, j = manager.IndexToNode(a), manager.IndexToNode(b)
        value = matrix.durations[i][j]
        return (
            1000000000
            if value is None
            else math.ceil((value + scenario.nodes[i].service_minutes) * scale)
        )

    distance_index = routing.RegisterTransitCallback(distance)
    routing.SetArcCostEvaluatorOfAllVehicles(distance_index)
    routing.SetFixedCostOfAllVehicles(unreachable)
    time_index = routing.RegisterTransitCallback(duration)
    horizon = math.floor(scenario.fleet.end_time * scale)
    departure = math.ceil(
        max(scenario.fleet.start_time, scenario.nodes[depot].window_start) * scale
    )
    return_limit = math.floor(
        min(scenario.fleet.end_time, scenario.nodes[depot].window_end) * scale
    )
    if departure > return_limit or any(
        math.ceil(n.window_start * scale) > min(horizon, math.floor(n.window_end * scale))
        for n in scenario.nodes
        if n.id != scenario.depot_id
    ):
        return  # Conservative integer model has an empty domain; not an original-model proof.
    routing.AddDimension(time_index, horizon, horizon, False, "Time")
    dimension = routing.GetDimensionOrDie("Time")
    for i, node in enumerate(scenario.nodes):
        if i != depot:
            dimension.CumulVar(manager.NodeToIndex(i)).SetRange(
                math.ceil(node.window_start * scale), math.floor(node.window_end * scale)
            )
    depot_node = scenario.nodes[depot]
    for vehicle in range(scenario.fleet.count):
        dimension.CumulVar(routing.Start(vehicle)).SetRange(departure, departure)
        dimension.CumulVar(routing.End(vehicle)).SetRange(
            departure, math.floor(min(scenario.fleet.end_time, depot_node.window_end) * scale)
        )
    demand_index = routing.RegisterUnaryTransitCallback(
        lambda a: math.ceil(scenario.nodes[manager.IndexToNode(a)].demand * scale)
    )
    routing.AddDimensionWithVehicleCapacity(
        demand_index,
        0,
        [math.floor(scenario.fleet.capacity * scale)] * scenario.fleet.count,
        True,
        "Capacity",
    )
    if scenario.fleet.max_distance_km is not None:
        routing.AddDimension(
            distance_index, 0, math.floor(scenario.fleet.max_distance_km * scale), True, "Distance"
        )
    for i in range(len(matrix.ids)):
        for j in range(len(matrix.ids)):
            if matrix.distances[i][j] is None:
                sources = (
                    [routing.Start(v) for v in range(scenario.fleet.count)]
                    if i == depot
                    else [manager.NodeToIndex(i)]
                )
                targets = (
                    [routing.End(v) for v in range(scenario.fleet.count)]
                    if j == depot
                    else [manager.NodeToIndex(j)]
                )
                for source in sources:
                    for target in targets:
                        routing.NextVar(source).RemoveValue(target)
    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    )
    parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    parameters.sat_parameters.random_seed = search.options.seed
    remaining = max(0.001, search.options.time_limit_seconds - search.elapsed())
    parameters.time_limit.FromMilliseconds(max(1, int(remaining * 1000)))

    stopped = None

    def at_solution():
        nonlocal stopped
        try:
            search.check()
        except SearchStopped as exc:
            stopped = exc
            routing.solver().FinishCurrentSearch()

    routing.AddAtSolutionCallback(at_solution)
    solution = routing.SolveWithParameters(parameters)
    if solution:
        routes = []
        for vehicle in range(scenario.fleet.count):
            index, route = routing.Start(vehicle), []
            while not routing.IsEnd(index):
                node_index = manager.IndexToNode(index)
                if node_index != depot:
                    route.append(matrix.ids[node_index])
                index = solution.Value(routing.NextVar(index))
            if route:
                routes.append(route)
        search.consider(routes, "OR-Tools reference (conservative scaling)")
    if stopped is not None:
        raise stopped
    search.check()
