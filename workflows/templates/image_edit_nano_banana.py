# /// script
# dependencies = []
#
# [tool.griptape-nodes]
# name = "image_edit_nano_banana"
# schema_version = "0.16.0"
# engine_version_created_with = "0.78.2"
# node_libraries_referenced = [["Nuke Nodes Library", "0.2.0"], ["Griptape Nodes Library", "0.68.0"]]
# node_types_used = [["Griptape Nodes Library", "GoogleImageGeneration"], ["Nuke Nodes Library", "NukeEndFlow"], ["Nuke Nodes Library", "NukeStartFlow"]]
# description = "Edit an image using Nano Banana"
# is_griptape_provided = true
# is_template = true
# creation_date = 2026-03-26T05:15:15.722176Z
# last_modified_date = 2026-03-26T05:23:33.368867Z
# workflow_shape = "{\"inputs\":{\"Nuke Start Flow\":{\"exec_out\":{\"name\":\"exec_out\",\"tooltip\":\"Connection to the next node in the execution chain\",\"type\":\"parametercontroltype\",\"input_types\":[\"parametercontroltype\"],\"output_type\":\"parametercontroltype\",\"default_value\":null,\"tooltip_as_input\":null,\"tooltip_as_property\":null,\"tooltip_as_output\":null,\"ui_options\":{\"display_name\":\"Flow Out\"},\"settable\":true,\"is_user_defined\":true,\"private\":false,\"parent_container_name\":null,\"parent_element_name\":null},\"input_image\":{\"name\":\"input_image\",\"tooltip\":\"Input image\",\"type\":\"ImageUrlArtifact\",\"input_types\":[\"any\"],\"output_type\":\"ImageUrlArtifact\",\"default_value\":null,\"tooltip_as_input\":null,\"tooltip_as_property\":null,\"tooltip_as_output\":null,\"ui_options\":{\"clickable_file_browser\":true,\"hide_label\":false,\"hide_property\":false},\"settable\":true,\"is_user_defined\":true,\"private\":false,\"parent_container_name\":null,\"parent_element_name\":null},\"prompt\":{\"name\":\"prompt\",\"tooltip\":\"Input text\",\"type\":\"str\",\"input_types\":[\"any\"],\"output_type\":\"str\",\"default_value\":null,\"tooltip_as_input\":null,\"tooltip_as_property\":null,\"tooltip_as_output\":null,\"ui_options\":{\"multiline\":true,\"placeholder_text\":\"Enter your prompt to manipulate the image here...\",\"hide_label\":false,\"hide_property\":false},\"settable\":true,\"is_user_defined\":true,\"private\":false,\"parent_container_name\":null,\"parent_element_name\":null},\"aspect_ratio\":{\"name\":\"aspect_ratio\",\"tooltip\":\"New parameter\",\"type\":\"str\",\"input_types\":[\"any\"],\"output_type\":\"str\",\"default_value\":\"\",\"tooltip_as_input\":null,\"tooltip_as_property\":null,\"tooltip_as_output\":null,\"ui_options\":{\"simple_dropdown\":[\"1:1\",\"3:2\",\"2:3\",\"3:4\",\"4:3\",\"4:5\",\"5:4\",\"9:16\",\"16:9\",\"21:9\"],\"show_search\":true,\"search_filter\":\"\",\"hide_label\":false,\"hide_property\":false,\"is_custom\":true,\"is_user_added\":true},\"settable\":true,\"is_user_defined\":true,\"private\":false,\"parent_container_name\":\"\",\"parent_element_name\":null},\"image_size\":{\"name\":\"image_size\",\"tooltip\":\"New parameter\",\"type\":\"str\",\"input_types\":[\"any\"],\"output_type\":\"str\",\"default_value\":\"\",\"tooltip_as_input\":null,\"tooltip_as_property\":null,\"tooltip_as_output\":null,\"ui_options\":{\"simple_dropdown\":[\"1K\",\"2K\",\"4K\"],\"show_search\":true,\"search_filter\":\"\",\"hide_label\":false,\"hide_property\":false,\"is_custom\":true,\"is_user_added\":true},\"settable\":true,\"is_user_defined\":true,\"private\":false,\"parent_container_name\":\"\",\"parent_element_name\":null},\"model\":{\"name\":\"model\",\"tooltip\":\"New parameter\",\"type\":\"str\",\"input_types\":[\"any\"],\"output_type\":\"str\",\"default_value\":\"\",\"tooltip_as_input\":null,\"tooltip_as_property\":null,\"tooltip_as_output\":null,\"ui_options\":{\"simple_dropdown\":[\"Nano Banana Pro\",\"Nano Banana 2\"],\"show_search\":true,\"search_filter\":\"\",\"display_name\":\"Model\",\"hide_label\":false,\"hide_property\":false,\"is_custom\":true,\"is_user_added\":true},\"settable\":true,\"is_user_defined\":true,\"private\":false,\"parent_container_name\":\"\",\"parent_element_name\":null}}},\"outputs\":{\"Nuke End Flow\":{\"exec_in\":{\"name\":\"exec_in\",\"tooltip\":\"Control path when the flow completed successfully\",\"type\":\"parametercontroltype\",\"input_types\":[\"parametercontroltype\"],\"output_type\":\"parametercontroltype\",\"default_value\":null,\"tooltip_as_input\":null,\"tooltip_as_property\":null,\"tooltip_as_output\":null,\"ui_options\":{\"display_name\":\"Succeeded\"},\"settable\":true,\"is_user_defined\":true,\"private\":false,\"parent_container_name\":null,\"parent_element_name\":null},\"failed\":{\"name\":\"failed\",\"tooltip\":\"Control path when the flow failed\",\"type\":\"parametercontroltype\",\"input_types\":[\"parametercontroltype\"],\"output_type\":\"parametercontroltype\",\"default_value\":null,\"tooltip_as_input\":null,\"tooltip_as_property\":null,\"tooltip_as_output\":null,\"ui_options\":{\"display_name\":\"Failed\"},\"settable\":true,\"is_user_defined\":true,\"private\":false,\"parent_container_name\":null,\"parent_element_name\":null},\"output_image\":{\"name\":\"output_image\",\"tooltip\":\"Output image\",\"type\":\"ImageUrlArtifact\",\"input_types\":[\"any\"],\"output_type\":\"ImageUrlArtifact\",\"default_value\":null,\"tooltip_as_input\":null,\"tooltip_as_property\":null,\"tooltip_as_output\":null,\"ui_options\":{\"clickable_file_browser\":true,\"hide_label\":false,\"hide_property\":false},\"settable\":true,\"is_user_defined\":true,\"private\":false,\"parent_container_name\":null,\"parent_element_name\":null},\"was_successful\":{\"name\":\"was_successful\",\"tooltip\":\"Indicates whether it completed without errors.\",\"type\":\"bool\",\"input_types\":[\"bool\"],\"output_type\":\"bool\",\"default_value\":false,\"tooltip_as_input\":null,\"tooltip_as_property\":null,\"tooltip_as_output\":null,\"ui_options\":{},\"settable\":false,\"is_user_defined\":true,\"private\":false,\"parent_container_name\":null,\"parent_element_name\":null},\"result_details\":{\"name\":\"result_details\",\"tooltip\":\"Details about the operation result\",\"type\":\"str\",\"input_types\":[\"str\"],\"output_type\":\"str\",\"default_value\":null,\"tooltip_as_input\":null,\"tooltip_as_property\":null,\"tooltip_as_output\":null,\"ui_options\":{\"multiline\":true,\"placeholder_text\":\"Details about the completion or failure will be shown here.\"},\"settable\":false,\"is_user_defined\":true,\"private\":false,\"parent_container_name\":null,\"parent_element_name\":null}}}}"
#
# ///

import argparse
import asyncio
import json
import logging
import pickle
from pathlib import Path

from griptape_nodes.bootstrap.workflow_executors.local_workflow_executor import LocalWorkflowExecutor
from griptape_nodes.bootstrap.workflow_executors.workflow_executor import WorkflowExecutor
from griptape_nodes.drivers.storage.storage_backend import StorageBackend
from griptape_nodes.node_library.library_registry import NodeMetadata
from griptape_nodes.retained_mode.events.connection_events import CreateConnectionRequest
from griptape_nodes.retained_mode.events.flow_events import (
    CreateFlowRequest,
    GetTopLevelFlowRequest,
    GetTopLevelFlowResultSuccess,
)
from griptape_nodes.retained_mode.events.library_events import RegisterLibraryFromFileRequest
from griptape_nodes.retained_mode.events.node_events import CreateNodeRequest
from griptape_nodes.retained_mode.events.parameter_events import (
    AddParameterToNodeRequest,
    AlterParameterDetailsRequest,
    SetParameterValueRequest,
)
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

GriptapeNodes.handle_request(
    RegisterLibraryFromFileRequest(library_name="Nuke Nodes Library", perform_discovery_if_not_found=True)
)

GriptapeNodes.handle_request(
    RegisterLibraryFromFileRequest(library_name="Griptape Nodes Library", perform_discovery_if_not_found=True)
)

context_manager = GriptapeNodes.ContextManager()

if not context_manager.has_current_workflow():
    context_manager.push_workflow(file_path=__file__)

"""
1. We've collated all of the unique parameter values into a dictionary so that we do not have to duplicate them.
   This minimizes the size of the code, especially for large objects like serialized image files.
2. We're using a prefix so that it's clear which Flow these values are associated with.
3. The values are serialized using pickle, which is a binary format. This makes them harder to read, but makes
   them consistently save and load. It allows us to serialize complex objects like custom classes, which otherwise
   would be difficult to serialize.
"""
top_level_unique_values_dict = {
    "e8629443-372c-4015-9b99-4604d416a6d4": pickle.loads(b"\x80\x04\x89."),
    "0d8415f7-1d85-4b5c-a7c9-65633251c390": pickle.loads(
        b"\x80\x04\x95\x08\x00\x00\x00\x00\x00\x00\x00\x8c\x0416:9\x94."
    ),
    "0482c06d-2e74-41cd-a0f4-6a377f879492": pickle.loads(
        b"\x80\x04\x95\x06\x00\x00\x00\x00\x00\x00\x00\x8c\x021K\x94."
    ),
    "2454be17-d560-437c-b121-0bca8da44bfb": pickle.loads(
        b"\x80\x04\x95\x11\x00\x00\x00\x00\x00\x00\x00\x8c\rNano Banana 2\x94."
    ),
    "632c71a2-764d-48e9-ba02-1735b94a2af8": pickle.loads(b"\x80\x04\x95\x04\x00\x00\x00\x00\x00\x00\x00\x8c\x00\x94."),
    "cd7d629b-a569-4085-a23b-c58ad0217042": pickle.loads(b"\x80\x04\x95\x06\x00\x00\x00\x00\x00\x00\x00]\x94]\x94a."),
    "fdf7ece2-3600-4cfa-83a7-b442b8f14c5a": pickle.loads(b"\x80\x04]\x94."),
    "35a575cf-7e73-4193-8c67-f2d5ba097e5a": pickle.loads(b"\x80\x04]\x94."),
    "29684ab5-aa87-4a3c-ae93-764854d4416b": pickle.loads(b"\x80\x04]\x94."),
    "01cf2857-139a-49a4-9a73-419f0f20901e": pickle.loads(b"\x80\x04\x88."),
    "4d4cf47a-d61f-41b8-9f4f-933cc4c85119": pickle.loads(
        b"\x80\x04\x95\n\x00\x00\x00\x00\x00\x00\x00G?\xf0\x00\x00\x00\x00\x00\x00."
    ),
    "718da06c-30d1-4138-8de7-4b03442e5aa6": pickle.loads(
        b"\x80\x04\x95\x18\x00\x00\x00\x00\x00\x00\x00\x8c\x14nanobanana_image.png\x94."
    ),
}

"# Create the Flow, then do work within it as context."

flow0_name = GriptapeNodes.handle_request(
    CreateFlowRequest(parent_flow_name=None, flow_name="ControlFlow_1", set_as_new_context=False, metadata={})
).flow_name

with GriptapeNodes.ContextManager().flow(flow0_name):
    node0_name = GriptapeNodes.handle_request(
        CreateNodeRequest(
            node_type="NukeEndFlow",
            specific_library_name="Nuke Nodes Library",
            node_name="Nuke End Flow",
            metadata={
                "position": {"x": 1751.6249566684057, "y": 583.2688442883341},
                "tempId": "placing-1774502125112-gq1jz",
                "library_node_metadata": NodeMetadata(
                    category="FoundryNuke",
                    description="End flow for Nuke",
                    display_name="Nuke End Flow",
                    tags=None,
                    icon="logos/nuke.png",
                    color=None,
                    group=None,
                    deprecation=None,
                    is_node_group=None,
                ),
                "library": "Nuke Nodes Library",
                "node_type": "NukeEndFlow",
                "showaddparameter": True,
                "size": {"width": 616, "height": 564},
                "category": "FoundryNuke",
            },
            initial_setup=True,
        )
    ).node_name
    node1_name = GriptapeNodes.handle_request(
        CreateNodeRequest(
            node_type="NukeStartFlow",
            specific_library_name="Nuke Nodes Library",
            node_name="Nuke Start Flow",
            metadata={
                "position": {"x": -273.6695915620044, "y": 560.0937644808978},
                "tempId": "placing-1774502126578-7uu0gv",
                "library_node_metadata": NodeMetadata(
                    category="FoundryNuke",
                    description="Start flow for Nuke",
                    display_name="Nuke Start Flow",
                    tags=None,
                    icon="logos/nuke.png",
                    color=None,
                    group=None,
                    deprecation=None,
                    is_node_group=None,
                ),
                "library": "Nuke Nodes Library",
                "node_type": "NukeStartFlow",
                "showaddparameter": True,
                "size": {"width": 600, "height": 663},
                "category": "FoundryNuke",
            },
            initial_setup=True,
        )
    ).node_name
    with GriptapeNodes.ContextManager().node(node1_name):
        GriptapeNodes.handle_request(
            AddParameterToNodeRequest(
                parameter_name="aspect_ratio",
                default_value="",
                tooltip="New parameter",
                type="str",
                input_types=["any"],
                output_type="str",
                ui_options={
                    "simple_dropdown": ["1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
                    "show_search": True,
                    "search_filter": "",
                    "hide_label": False,
                    "hide_property": False,
                    "is_custom": True,
                    "is_user_added": True,
                },
                parent_container_name="",
                initial_setup=True,
            )
        )
        GriptapeNodes.handle_request(
            AddParameterToNodeRequest(
                parameter_name="image_size",
                default_value="",
                tooltip="New parameter",
                type="str",
                input_types=["any"],
                output_type="str",
                ui_options={
                    "simple_dropdown": ["1K", "2K", "4K"],
                    "show_search": True,
                    "search_filter": "",
                    "hide_label": False,
                    "hide_property": False,
                    "is_custom": True,
                    "is_user_added": True,
                },
                parent_container_name="",
                initial_setup=True,
            )
        )
        GriptapeNodes.handle_request(
            AddParameterToNodeRequest(
                parameter_name="model",
                default_value="",
                tooltip="New parameter",
                type="str",
                input_types=["any"],
                output_type="str",
                ui_options={
                    "simple_dropdown": ["Nano Banana Pro", "Nano Banana 2"],
                    "show_search": True,
                    "search_filter": "",
                    "display_name": "Model",
                    "hide_label": False,
                    "hide_property": False,
                    "is_custom": True,
                    "is_user_added": True,
                },
                parent_container_name="",
                initial_setup=True,
            )
        )
    node2_name = GriptapeNodes.handle_request(
        CreateNodeRequest(
            node_type="GoogleImageGeneration",
            specific_library_name="Griptape Nodes Library",
            node_name="Google Nano Banana Image Generation",
            metadata={
                "position": {"x": 813.4078103830899, "y": 560.0937644808978},
                "tempId": "placing-1774502375523-fk8qg3",
                "library_node_metadata": {
                    "category": "image",
                    "description": "Generate images using Google models via Griptape model proxy",
                },
                "library": "Griptape Nodes Library",
                "node_type": "GoogleImageGeneration",
                "showaddparameter": False,
                "size": {"width": 600, "height": 944},
                "category": "image",
            },
            initial_setup=True,
        )
    ).node_name
    with GriptapeNodes.ContextManager().node(node2_name):
        GriptapeNodes.handle_request(
            AddParameterToNodeRequest(
                parameter_name="input_images_ParameterListUniqueParamID_0557a905b7374b7f9fedd9ff8c24c80d",
                default_value=[],
                tooltip="Optional reference images for the generation",
                type="ImageUrlArtifact",
                input_types=["ImageUrlArtifact", "ImageArtifact", "str"],
                output_type="ImageUrlArtifact",
                ui_options={"display_name": "Input Images", "expander": True},
                mode_allowed_property=False,
                mode_allowed_output=False,
                parent_container_name="input_images",
                initial_setup=True,
            )
        )
        GriptapeNodes.handle_request(
            AlterParameterDetailsRequest(
                parameter_name="aspect_ratio",
                ui_options={
                    "simple_dropdown": [
                        "1:1",
                        "1:4",
                        "1:8",
                        "2:3",
                        "3:2",
                        "3:4",
                        "4:1",
                        "4:3",
                        "4:5",
                        "5:4",
                        "8:1",
                        "9:16",
                        "16:9",
                        "21:9",
                    ],
                    "show_search": True,
                    "search_filter": "",
                    "hide_label": False,
                    "hide_property": False,
                },
                initial_setup=True,
            )
        )
        GriptapeNodes.handle_request(
            AlterParameterDetailsRequest(
                parameter_name="image_size",
                ui_options={
                    "simple_dropdown": ["512", "1K", "2K", "4K"],
                    "show_search": True,
                    "search_filter": "",
                    "hide_label": False,
                    "hide_property": False,
                },
                initial_setup=True,
            )
        )
        GriptapeNodes.handle_request(
            AlterParameterDetailsRequest(
                parameter_name="use_google_image_search",
                ui_options={"hide": False, "hide_label": False, "hide_property": False},
                initial_setup=True,
            )
        )
    GriptapeNodes.handle_request(
        CreateConnectionRequest(
            source_node_name=node1_name,
            source_parameter_name="input_image",
            target_node_name=node2_name,
            target_parameter_name="input_images_ParameterListUniqueParamID_0557a905b7374b7f9fedd9ff8c24c80d",
            initial_setup=True,
        )
    )
    GriptapeNodes.handle_request(
        CreateConnectionRequest(
            source_node_name=node1_name,
            source_parameter_name="prompt",
            target_node_name=node2_name,
            target_parameter_name="prompt",
            initial_setup=True,
        )
    )
    GriptapeNodes.handle_request(
        CreateConnectionRequest(
            source_node_name=node2_name,
            source_parameter_name="image",
            target_node_name=node0_name,
            target_parameter_name="output_image",
            initial_setup=True,
        )
    )
    GriptapeNodes.handle_request(
        CreateConnectionRequest(
            source_node_name=node1_name,
            source_parameter_name="aspect_ratio",
            target_node_name=node2_name,
            target_parameter_name="aspect_ratio",
            initial_setup=True,
        )
    )
    GriptapeNodes.handle_request(
        CreateConnectionRequest(
            source_node_name=node1_name,
            source_parameter_name="image_size",
            target_node_name=node2_name,
            target_parameter_name="image_size",
            initial_setup=True,
        )
    )
    GriptapeNodes.handle_request(
        CreateConnectionRequest(
            source_node_name=node1_name,
            source_parameter_name="model",
            target_node_name=node2_name,
            target_parameter_name="model",
            initial_setup=True,
        )
    )
    with GriptapeNodes.ContextManager().node(node0_name):
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="was_successful",
                node_name=node0_name,
                value=top_level_unique_values_dict["e8629443-372c-4015-9b99-4604d416a6d4"],
                initial_setup=True,
                is_output=False,
            )
        )
    with GriptapeNodes.ContextManager().node(node1_name):
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="aspect_ratio",
                node_name=node1_name,
                value=top_level_unique_values_dict["0d8415f7-1d85-4b5c-a7c9-65633251c390"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="image_size",
                node_name=node1_name,
                value=top_level_unique_values_dict["0482c06d-2e74-41cd-a0f4-6a377f879492"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="model",
                node_name=node1_name,
                value=top_level_unique_values_dict["2454be17-d560-437c-b121-0bca8da44bfb"],
                initial_setup=True,
                is_output=False,
            )
        )
    with GriptapeNodes.ContextManager().node(node2_name):
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="model",
                node_name=node2_name,
                value=top_level_unique_values_dict["2454be17-d560-437c-b121-0bca8da44bfb"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="prompt",
                node_name=node2_name,
                value=top_level_unique_values_dict["632c71a2-764d-48e9-ba02-1735b94a2af8"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="input_images",
                node_name=node2_name,
                value=top_level_unique_values_dict["cd7d629b-a569-4085-a23b-c58ad0217042"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="input_images_ParameterListUniqueParamID_0557a905b7374b7f9fedd9ff8c24c80d",
                node_name=node2_name,
                value=top_level_unique_values_dict["fdf7ece2-3600-4cfa-83a7-b442b8f14c5a"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="object_images",
                node_name=node2_name,
                value=top_level_unique_values_dict["35a575cf-7e73-4193-8c67-f2d5ba097e5a"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="human_images",
                node_name=node2_name,
                value=top_level_unique_values_dict["29684ab5-aa87-4a3c-ae93-764854d4416b"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="aspect_ratio",
                node_name=node2_name,
                value=top_level_unique_values_dict["0d8415f7-1d85-4b5c-a7c9-65633251c390"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="image_size",
                node_name=node2_name,
                value=top_level_unique_values_dict["0482c06d-2e74-41cd-a0f4-6a377f879492"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="auto_image_resize",
                node_name=node2_name,
                value=top_level_unique_values_dict["01cf2857-139a-49a4-9a73-419f0f20901e"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="temperature",
                node_name=node2_name,
                value=top_level_unique_values_dict["4d4cf47a-d61f-41b8-9f4f-933cc4c85119"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="use_google_search",
                node_name=node2_name,
                value=top_level_unique_values_dict["e8629443-372c-4015-9b99-4604d416a6d4"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="use_google_image_search",
                node_name=node2_name,
                value=top_level_unique_values_dict["e8629443-372c-4015-9b99-4604d416a6d4"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="output_file",
                node_name=node2_name,
                value=top_level_unique_values_dict["718da06c-30d1-4138-8de7-4b03442e5aa6"],
                initial_setup=True,
                is_output=False,
            )
        )
        GriptapeNodes.handle_request(
            SetParameterValueRequest(
                parameter_name="was_successful",
                node_name=node2_name,
                value=top_level_unique_values_dict["e8629443-372c-4015-9b99-4604d416a6d4"],
                initial_setup=True,
                is_output=False,
            )
        )


def _ensure_workflow_context():
    context_manager = GriptapeNodes.ContextManager()
    if not context_manager.has_current_flow():
        top_level_flow_request = GetTopLevelFlowRequest()
        top_level_flow_result = GriptapeNodes.handle_request(top_level_flow_request)
        if (
            isinstance(top_level_flow_result, GetTopLevelFlowResultSuccess)
            and top_level_flow_result.flow_name is not None
        ):
            flow_manager = GriptapeNodes.FlowManager()
            flow_obj = flow_manager.get_flow_by_name(top_level_flow_result.flow_name)
            context_manager.push_flow(flow_obj)


def execute_workflow(
    input: dict,
    storage_backend: str = "local",
    project_file_path: str | None = None,
    workflow_executor: WorkflowExecutor | None = None,
    pickle_control_flow_result: bool = False,
) -> dict | None:
    return asyncio.run(
        aexecute_workflow(
            input=input,
            storage_backend=storage_backend,
            project_file_path=project_file_path,
            workflow_executor=workflow_executor,
            pickle_control_flow_result=pickle_control_flow_result,
        )
    )


async def aexecute_workflow(
    input: dict,
    storage_backend: str = "local",
    project_file_path: str | None = None,
    workflow_executor: WorkflowExecutor | None = None,
    pickle_control_flow_result: bool = False,
) -> dict | None:
    _ensure_workflow_context()
    storage_backend_enum = StorageBackend(storage_backend)
    project_file_path_resolved = Path(project_file_path) if project_file_path is not None else None
    workflow_executor = workflow_executor or LocalWorkflowExecutor(
        storage_backend=storage_backend_enum,
        project_file_path=project_file_path_resolved,
        skip_library_loading=True,
        workflows_to_register=[__file__],
    )
    async with workflow_executor as executor:
        await executor.arun(flow_input=input, pickle_control_flow_result=pickle_control_flow_result)
    return executor.output


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--storage-backend",
        choices=["local", "gtc"],
        default="local",
        help="Storage backend to use: 'local' for local filesystem or 'gtc' for Griptape Cloud",
    )
    parser.add_argument(
        "--project-file-path", default=None, help="Path to a project file to load for the workflow execution"
    )
    parser.add_argument(
        "--json-input",
        default=None,
        help="JSON string containing parameter values. Takes precedence over individual parameter arguments if provided.",
    )
    parser.add_argument("--exec_out", default=None, help="Connection to the next node in the execution chain")
    parser.add_argument("--input_image", default=None, help="Input image")
    parser.add_argument("--prompt", default=None, help="Input text")
    parser.add_argument("--aspect_ratio", default=None, help="New parameter")
    parser.add_argument("--image_size", default=None, help="New parameter")
    parser.add_argument("--model", default=None, help="New parameter")
    args = parser.parse_args()
    flow_input = {}
    if args.json_input is not None:
        flow_input = json.loads(args.json_input)
    if args.json_input is None:
        if "Nuke Start Flow" not in flow_input:
            flow_input["Nuke Start Flow"] = {}
        if args.exec_out is not None:
            flow_input["Nuke Start Flow"]["exec_out"] = args.exec_out
        if args.input_image is not None:
            flow_input["Nuke Start Flow"]["input_image"] = args.input_image
        if args.prompt is not None:
            flow_input["Nuke Start Flow"]["prompt"] = args.prompt
        if args.aspect_ratio is not None:
            flow_input["Nuke Start Flow"]["aspect_ratio"] = args.aspect_ratio
        if args.image_size is not None:
            flow_input["Nuke Start Flow"]["image_size"] = args.image_size
        if args.model is not None:
            flow_input["Nuke Start Flow"]["model"] = args.model
    workflow_output = execute_workflow(
        input=flow_input, storage_backend=args.storage_backend, project_file_path=args.project_file_path
    )
    print(workflow_output)
