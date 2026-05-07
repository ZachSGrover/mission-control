"""Model exports for SQLAlchemy/SQLModel metadata discovery."""

from app.models.activity_events import ActivityEvent
from app.models.agents import Agent
from app.models.app_setting import AppSetting
from app.models.approval_task_links import ApprovalTaskLink
from app.models.approvals import Approval
from app.models.audit_event import AuditEvent
from app.models.board_group_memory import BoardGroupMemory
from app.models.board_groups import BoardGroup
from app.models.board_memory import BoardMemory
from app.models.board_onboarding import BoardOnboardingSession
from app.models.board_webhook_payloads import BoardWebhookPayload
from app.models.board_webhooks import BoardWebhook
from app.models.boards import Board
from app.models.bot_contact_archive import BotContactArchive
from app.models.bot_registry import BotRegistryEntry
from app.models.bot_runs import BotRun, BotRunOutput
from app.models.client_consents import ClientConsent
from app.models.connector_approvals import ConnectorApproval
from app.models.creator_credentials import CreatorCredential
from app.models.gateways import Gateway
from app.models.kill_switches import KillSwitch
from app.models.of_intelligence import (
    BusinessMemoryEntry,
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceChat,
    OfIntelligenceChatter,
    OfIntelligenceFan,
    OfIntelligenceMassMessage,
    OfIntelligenceMessage,
    OfIntelligencePost,
    OfIntelligenceQcReport,
    OfIntelligenceRevenue,
    OfIntelligenceSyncLog,
    OfIntelligenceTrackingLink,
)
from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.models.of_qc_finding import OfIntelligenceQcFinding
from app.models.of_qc_scheduler_job import OfQcSchedulerJob
from app.models.organization_board_access import OrganizationBoardAccess
from app.models.organization_invite_board_access import OrganizationInviteBoardAccess
from app.models.organization_invites import OrganizationInvite
from app.models.organization_members import OrganizationMember
from app.models.organizations import Organization
from app.models.safety_events import SafetyEvent
from app.models.skills import GatewayInstalledSkill, MarketplaceSkill, SkillPack
from app.models.tag_assignments import TagAssignment
from app.models.tags import Tag
from app.models.task_custom_fields import (
    BoardTaskCustomField,
    TaskCustomFieldDefinition,
    TaskCustomFieldValue,
)
from app.models.task_dependencies import TaskDependency
from app.models.task_fingerprints import TaskFingerprint
from app.models.tasks import Task
from app.models.usage import UsageAlertConfig, UsageEvent, UsageSnapshot
from app.models.users import User

__all__ = [
    "AppSetting",
    "ActivityEvent",
    "Agent",
    "AuditEvent",
    "BotContactArchive",
    "BotRegistryEntry",
    "BotRun",
    "BotRunOutput",
    "ApprovalTaskLink",
    "Approval",
    "BoardGroupMemory",
    "BoardWebhook",
    "BoardWebhookPayload",
    "BoardMemory",
    "BoardOnboardingSession",
    "BoardGroup",
    "Board",
    "ClientConsent",
    "ConnectorApproval",
    "CreatorCredential",
    "Gateway",
    "KillSwitch",
    "GatewayInstalledSkill",
    "MarketplaceSkill",
    "SkillPack",
    "Organization",
    "BusinessMemoryEntry",
    "OfIntelligenceAccount",
    "OfIntelligenceAlert",
    "OfIntelligenceChat",
    "OfIntelligenceChatter",
    "OfIntelligenceFan",
    "OfIntelligenceMassMessage",
    "OfIntelligenceMessage",
    "OfIntelligencePost",
    "OfIntelligenceQcReport",
    "OfIntelligenceRevenue",
    "OfIntelligenceSyncLog",
    "OfIntelligenceTrackingLink",
    "OfIntelligenceQcFinding",
    "OfQcDiscordStatus",
    "OfQcSchedulerJob",
    "BoardTaskCustomField",
    "TaskCustomFieldDefinition",
    "TaskCustomFieldValue",
    "OrganizationMember",
    "OrganizationBoardAccess",
    "OrganizationInvite",
    "OrganizationInviteBoardAccess",
    "SafetyEvent",
    "TaskDependency",
    "Task",
    "TaskFingerprint",
    "Tag",
    "TagAssignment",
    "UsageAlertConfig",
    "UsageEvent",
    "UsageSnapshot",
    "User",
]
