"""Amazon SNS tools for the MCP server."""
import boto3
import json
from aws_service_mcp_generator.generator import BOTO3_CLIENT_GETTER, AWSToolGenerator
from awslabs.amazon_sns_sqs_mcp_server.consts import MCP_SERVER_VERSION
from awslabs.amazon_sns_sqs_mcp_server.common import validate_mcp_server_version_tag, MCP_SERVER_VERSION_TAG
from mcp.server.fastmcp import FastMCP
from typing import Any, Dict, List

# override create_topic tool to tag resources
def create_topic_override(mcp: FastMCP, sns_client_getter: BOTO3_CLIENT_GETTER, _: str):
    """Create an SNS topic with MCP server version tag."""

    @mcp.tool()
    def handle_create_topic(
        name: str,
        attributes: Dict[str, str] = {},
        tags: List[Dict[str, str]] = [],
        region: str = 'us-east-1',
    ):
        create_params = {
            'Name': name,
            'Attributes': attributes.copy(),  # Create a copy to avoid modifying the original
        }
            
        # Set FIFO topic attributes if name ends with .fifo
        if name.endswith(".fifo"):
            create_params['Attributes']["FifoTopic"] = "true"
            create_params['Attributes']["FifoThroughputScope"] = "MessageGroup"
            
        # Add MCP server version tag
        tags_copy = tags.copy()  
        tags_copy.append({
            'Key': MCP_SERVER_VERSION_TAG,
            'Value': MCP_SERVER_VERSION
        })
        
        create_params['Tags'] = tags_copy
        
        sns_client = sns_client_getter(region)
        response = sns_client.create_topic(**create_params)
        return response


# Define validator for SNS resources
def is_mutative_action_allowed(
    mcp: FastMCP, sns_client: boto3.client, kwargs: Dict[str, Any]
) -> tuple[bool, str]:
    """Check if the SNS resource being mutated is tagged with mcp_server_version."""
    # Check for TopicArn (used by most operations)
    resource_arn = kwargs.get('TopicArn')
    
    if resource_arn is None or resource_arn == '':
        return False, f'TopicArn is not passed to the tool'
    
    try:
        tags = sns_client.list_tags_for_resource(ResourceArn=resource_arn)
        tag_dict = {tag.get('Key'): tag.get('Value') for tag in tags.get('Tags', [])}
        return validate_mcp_server_version_tag(tag_dict)
    except Exception as e:
        return False, str(e)


# Define validator specifically for unsubscribe operation
def is_unsubscribe_allowed(
    mcp: FastMCP, sns_client: boto3.client, kwargs: Dict[str, Any]
) -> tuple[bool, str]:
    """Check if the SNS subscription being unsubscribed is from a tagged topic."""
    subscription_arn = kwargs.get('SubscriptionArn')
    
    if subscription_arn is None or subscription_arn == '':
        return False, f'SubscriptionArn is not passed to the tool'
    
    try:
        # Get subscription attributes to find the TopicArn
        attributes = sns_client.get_subscription_attributes(SubscriptionArn=subscription_arn)
        topic_arn = attributes.get('Attributes', {}).get('TopicArn')
        
        return is_mutative_action_allowed(mcp, sns_client, {"TopicArn": topic_arn})

    except Exception as e:
        return False, str(e)
        


def set_archive_policy_override(mcp: FastMCP, sns_client_getter: BOTO3_CLIENT_GETTER, _: str):
    """Set or remove an archive policy for an SNS FIFO topic."""

    @mcp.tool()
    def handle_set_archive_policy(
        topic_arn: str,
        retention_period_days: int = 7,
        region: str = 'us-east-1',
    ):
        """
        Set an archive policy for an SNS FIFO topic.

        Args:
            topic_arn: The ARN of the SNS topic
            retention_period_days: Number of days to retain messages (1-365)
            region: AWS region

        Returns:
            Dict with operation status and details
        """
        # Validate retention period
        if not 1 <= retention_period_days <= 365:
            return {
                "error": "Retention period must be between 1 and 365 days",
                "code": "ValidationError",
            }

        # Create archive policy
        archive_policy = {"MessageRetentionPeriod": retention_period_days}
        policy_str = json.dumps(archive_policy)

        # Set topic attributes
        operation_kwargs = {
            "TopicArn": topic_arn,
            "AttributeName": "ArchivePolicy",
            "AttributeValue": policy_str,
        }

        sns_client = sns_client_getter(region)
        try:
            response = sns_client.set_topic_attributes(**operation_kwargs)
            return {
                "success": True,
                "topic_arn": topic_arn,
                "message": f"Archive policy set successfully with retention period of {retention_period_days} days",
                "retention_period_days": retention_period_days
            }
        except Exception as e:
            return {
                "error": str(e),
                "code": type(e).__name__,
            }


def remove_archive_policy_override(mcp: FastMCP, sns_client_getter: BOTO3_CLIENT_GETTER, _: str):
    """Remove an archive policy from an SNS FIFO topic."""

    @mcp.tool()
    def handle_remove_archive_policy(
        topic_arn: str,
        region: str = 'us-east-1',
    ):
        """
        Remove an archive policy from an SNS FIFO topic.

        Args:
            topic_arn: The ARN of the SNS topic
            region: AWS region

        Returns:
            Dict with operation status and details
        """
        # Empty archive policy
        archive_policy = {}
        policy_str = json.dumps(archive_policy)

        # Set topic attributes
        operation_kwargs = {
            "TopicArn": topic_arn,
            "AttributeName": "ArchivePolicy",
            "AttributeValue": policy_str,
        }

        sns_client = sns_client_getter(region)
        try:
            response = sns_client.set_topic_attributes(**operation_kwargs)
            return {
                "success": True,
                "topic_arn": topic_arn,
                "message": "Archive policy removed successfully"
            }
        except Exception as e:
            return {
                "error": str(e),
                "code": type(e).__name__,
            }


def register_sns_tools(mcp: FastMCP):
    """Register SNS tools with the MCP server."""
    # Generate SNS tools
    sns_generator = AWSToolGenerator(
        service_name='sns',
        service_display_name='Amazon SNS',
        mcp=mcp,
        tool_configuration={
            'close': {'ignore': True},
            'can_paginate': {'ignore': True},
            'generate_presigned_url': {'ignore': True},
            'untag_resource': {'ignore': True},
            'tag_resource': {'ignore': True},
            'create_topic': {'func_override': create_topic_override},
            'delete_topic': {'validator': is_mutative_action_allowed},
            'set_topic_attributes': {'validator': is_mutative_action_allowed},
            'subscribe': {'validator': is_mutative_action_allowed},
            'unsubscribe': {'validator': is_unsubscribe_allowed},
            'confirm_subscription': {'validator': is_mutative_action_allowed},
            'publish': {'validator': is_mutative_action_allowed},
            'publish_batch': {'validator': is_mutative_action_allowed},
            'set_archive_policy': {'func_override': set_archive_policy_override, 'validator': is_mutative_action_allowed},
            'remove_archive_policy': {'func_override': remove_archive_policy_override, 'validator': is_mutative_action_allowed},
        },
    )
    sns_generator.generate()
