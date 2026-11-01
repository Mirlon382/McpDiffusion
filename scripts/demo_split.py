"""Exercise the INSEE bricks, aggregate and gateway over Streamable HTTP."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping
from typing import Any

from fastmcp import Client

QUESTION = "Explorer l'IPC : publication, série détaillée, métadonnées."
INSEE_QUERY = "indice des prix à la consommation inflation prix"
MELODI_QUERY = "indice des prix a la consommation"
RMES_GRAPH_FILTER = "produits"
OBSERVATION_LIMIT = 3


def parse_arguments() -> argparse.Namespace:
    """Read the running server URLs from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--insee-url", required=True)
    parser.add_argument("--melodi-url", required=True)
    parser.add_argument("--rmes-url", required=True)
    parser.add_argument("--aggregate-url", required=True)
    parser.add_argument("--gateway-url", required=True)
    parser.add_argument("--failure-demo", action="store_true")
    return parser.parse_args()


def json_value(value: Any) -> Any:
    """Convert FastMCP structured output to JSON-compatible values."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def brief(value: Any) -> Any:
    """Keep the live walkthrough readable while preserving returned source values."""
    data = json_value(value)
    if not isinstance(data, dict):
        return data
    if "indicators" in data:
        return {
            "count": data.get("count"),
            "indicators": data["indicators"][:3],
        }
    if "results" in data:
        return {key: item[:2] if isinstance(item, list) else item for key, item in data.items()}
    if "observations" in data:
        return {
            "dataset_id": data.get("dataset_id"),
            "count": data.get("count"),
            "observations": data["observations"][:OBSERVATION_LIMIT],
        }
    if "categories" in data:
        categories = data["categories"]
        return {
            "total_graphs_matched": data.get("total_graphs_matched"),
            "categories": [
                {
                    "category": item.get("category"),
                    "label": item.get("label"),
                    "count": item.get("count"),
                    "examples": item.get("examples", [])[:2],
                }
                for item in categories[:3]
            ],
        }
    return data


async def invoke(url: str, name: str, arguments: dict[str, Any]) -> Any:
    """Call one tool and return its structured data, or its real protocol error."""
    async with Client(url) as client:
        result = await client.call_tool(name, arguments)
    if result.is_error:
        message = result.content[0].text if result.content else "Unknown MCP tool error"
        raise RuntimeError(f"{name} failed: {message}")
    if result.structured_content is None:
        raise RuntimeError(f"{name} returned no structured MCP content")
    return result.structured_content


async def route_via_gateway(
    client: Client[Any],
    *,
    expected_tool: str,
    discovery_query: str,
    arguments: dict[str, Any],
) -> Any:
    """Discover the upstream tool, then ask the gateway to call its namespaced name."""
    search_result = await client.call_tool(
        "search_tools",
        {"query": f"{expected_tool} {discovery_query}"},
    )
    search_text = "\n".join(block.text for block in search_result.content if hasattr(block, "text"))
    if search_result.is_error:
        raise RuntimeError("Gateway tool discovery failed")
    if expected_tool not in search_text:
        raise RuntimeError(f"Gateway search did not return {expected_tool}")
    routed = await client.call_tool(
        "call_tool",
        {
            "name": expected_tool,
            "arguments": arguments,
        },
    )
    if routed.is_error:
        message = routed.content[0].text if routed.content else "Unknown MCP tool error"
        raise RuntimeError(f"Gateway call to {expected_tool} failed: {message}")
    if routed.structured_content is None:
        raise RuntimeError(f"Gateway call to {expected_tool} returned no structured MCP content")
    return routed.structured_content


async def failure_demo(gateway_url: str) -> None:
    """Show that a stopped INSEE brick fails locally while RMES still answers."""
    async with Client(gateway_url) as client:
        try:
            await route_via_gateway(
                client,
                expected_tool="insee_search_insee_conjoncture",
                discovery_query="monthly INSEE rapid releases on inflation and consumer prices",
                arguments={"query": INSEE_QUERY, "number_of_results": 2},
            )
        except RuntimeError as error:
            print(f"INSEE through gateway: unavailable ({error})")
        else:
            raise RuntimeError("The stopped INSEE brick unexpectedly answered through the gateway")
        rmes_data = await route_via_gateway(
            client,
            expected_tool="rmes_search_rmes_graphs",
            discovery_query="discover RMES named RDF metadata graphs and categories",
            arguments={"graph_uri_substring": RMES_GRAPH_FILTER},
        )
    print("RMES through the same gateway: still available")
    print(json.dumps(brief(rmes_data), ensure_ascii=False, indent=2))


async def live_demo(urls: argparse.Namespace) -> None:
    """Compare direct, aggregate and gateway results, then route across all bricks."""
    print(f"Question: {QUESTION}")

    insee_direct = await invoke(urls.insee_url, "get_insee_homepage", {})
    aggregate_same_question = await invoke(urls.aggregate_url, "get_insee_homepage", {})
    if json.dumps(json_value(insee_direct), sort_keys=True) != json.dumps(
        json_value(aggregate_same_question),
        sort_keys=True,
    ):
        raise RuntimeError("Direct INSEE and aggregate homepage data differ")
    print("INSEE brick → get_insee_homepage")
    print(json.dumps(brief(insee_direct), ensure_ascii=False, indent=2))
    print("Aggregate → get_insee_homepage (same returned data: yes)")
    print(json.dumps(brief(aggregate_same_question), ensure_ascii=False, indent=2))

    insee_publications = await invoke(
        urls.insee_url,
        "search_insee_conjoncture",
        {"query": INSEE_QUERY, "number_of_results": 3},
    )
    aggregate_insee_publications = await invoke(
        urls.aggregate_url,
        "search_insee_conjoncture",
        {"query": INSEE_QUERY, "number_of_results": 3},
    )
    if json.dumps(json_value(insee_publications), sort_keys=True) != json.dumps(
        json_value(aggregate_insee_publications),
        sort_keys=True,
    ):
        raise RuntimeError("Direct INSEE and aggregate publication results differ")
    print("INSEE brick → search_insee_conjoncture")
    print(json.dumps(brief(insee_publications), ensure_ascii=False, indent=2))
    print("Aggregate → search_insee_conjoncture (same returned data: yes)")

    melodi_data = await invoke(
        urls.melodi_url,
        "search_melodi_datasets",
        {"query": MELODI_QUERY, "number_of_datasets": 3},
    )
    print("MELODI brick → search_melodi_datasets")
    print(json.dumps(brief(melodi_data), ensure_ascii=False, indent=2))
    dataset_id = melodi_data["results"][0]["dataset_id"]
    melodi_observations = await invoke(
        urls.melodi_url,
        "get_melodi_observations",
        {
            "dataset_id": dataset_id,
            "number_of_observations": OBSERVATION_LIMIT,
        },
    )
    print("MELODI brick → get_melodi_observations (first discovered dataset)")
    print(json.dumps(brief(melodi_observations), ensure_ascii=False, indent=2))

    rmes_data = await invoke(
        urls.rmes_url,
        "search_rmes_graphs",
        {"graph_uri_substring": RMES_GRAPH_FILTER},
    )
    print("RMES brick → search_rmes_graphs")
    print(json.dumps(brief(rmes_data), ensure_ascii=False, indent=2))

    async with Client(urls.gateway_url) as gateway:
        gateway_homepage = await route_via_gateway(
            gateway,
            expected_tool="insee_get_insee_homepage",
            discovery_query="INSEE homepage key indicators inflation unemployment GDP",
            arguments={},
        )
        if json.dumps(json_value(insee_direct), sort_keys=True) != json.dumps(
            json_value(gateway_homepage),
            sort_keys=True,
        ):
            raise RuntimeError("Direct INSEE and gateway homepage data differ")
        print("Gateway search_tools → call_tool(insee_get_insee_homepage; same data: yes)")

        gateway_insee = await route_via_gateway(
            gateway,
            expected_tool="insee_search_insee_conjoncture",
            discovery_query="monthly INSEE rapid releases on inflation and consumer prices",
            arguments={"query": INSEE_QUERY, "number_of_results": 3},
        )
        gateway_melodi = await route_via_gateway(
            gateway,
            expected_tool="melodi_search_melodi_datasets",
            discovery_query="MELODI statistical dataset catalogue search price index consumer prices",
            arguments={"query": MELODI_QUERY, "number_of_datasets": 3},
        )
        gateway_dataset_id = gateway_melodi["results"][0]["dataset_id"]
        if dataset_id != gateway_dataset_id:
            raise RuntimeError("Direct MELODI and gateway selected different first datasets")
        gateway_melodi_observations = await route_via_gateway(
            gateway,
            expected_tool="melodi_get_melodi_observations",
            discovery_query="MELODI retrieve detailed statistical observations for a dataset",
            arguments={
                "dataset_id": gateway_dataset_id,
                "number_of_observations": OBSERVATION_LIMIT,
            },
        )
        gateway_rmes = await route_via_gateway(
            gateway,
            expected_tool="rmes_search_rmes_graphs",
            discovery_query="RMES named RDF metadata graphs definitions classifications",
            arguments={"graph_uri_substring": RMES_GRAPH_FILTER},
        )
        direct_gateway_pairs = (
            ("INSEE publications", insee_publications, gateway_insee),
            ("MELODI datasets", melodi_data, gateway_melodi),
            ("MELODI observations", melodi_observations, gateway_melodi_observations),
            ("RMES graph discovery", rmes_data, gateway_rmes),
        )
        for label, direct_result, gateway_result in direct_gateway_pairs:
            if json.dumps(json_value(direct_result), sort_keys=True) != json.dumps(
                json_value(gateway_result),
                sort_keys=True,
            ):
                raise RuntimeError(f"Direct and gateway results differ for {label}")

    print("Gateway returned the same homepage data as the INSEE brick: yes")
    print("Gateway returned the same structured data as each brick: yes")
    print("Gateway routes the same topic across INSEE, MELODI and RMES:")
    for label, data in (
        ("insee_search_insee_conjoncture", gateway_insee),
        ("melodi_search_melodi_datasets", gateway_melodi),
        ("melodi_get_melodi_observations", gateway_melodi_observations),
        ("rmes_search_rmes_graphs", gateway_rmes),
    ):
        print(f"{label}")
        print(json.dumps(brief(data), ensure_ascii=False, indent=2))


async def main() -> None:
    """Run the regular or failure walkthrough."""
    urls = parse_arguments()
    if urls.failure_demo:
        await failure_demo(urls.gateway_url)
    else:
        await live_demo(urls)


if __name__ == "__main__":
    asyncio.run(main())
