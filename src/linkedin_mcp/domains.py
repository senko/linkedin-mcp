"""Names and descriptions of Member Snapshot domains.

Source: https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/shared/snapshot-domain

Domain names are case-sensitive. The API is not fully consistent with the
documentation: it returns events as "Events" (the documented "EVENTS" is rejected with
HTTP 400) and also returns the undocumented "WHATSAPP_NUMBERS" domain.
"""

INBOX = "INBOX"
CONNECTIONS = "CONNECTIONS"
PROFILE = "PROFILE"
MEMBER_SHARE_INFO = "MEMBER_SHARE_INFO"

DOMAIN_DESCRIPTIONS: dict[str, str] = {
    "ACCOUNT_HISTORY": "Date and time the account status changed within the last year.",
    "ACTOR_SAVE_ITEM": "Saved date and URL of saved posts, articles and other content.",
    "AD_TARGETING": "Information LinkedIn uses to decide which ads to show.",
    "ADS_CLICKED": "Ads the member clicked on.",
    "ADS_LAN": "LinkedIn Audience Network ad engagement.",
    "ALL_COMMENTS": "Comments the member made, excluding comments on posts in Groups.",
    "ALL_LIKES": "Reactions the member made to posts.",
    "ALL_VOTES": "Polls the member created and voted on.",
    "ARTICLES": "Articles authored by the member.",
    "CAUSES_YOU_CARE_ABOUT": "Causes listed on the profile.",
    "CERTIFICATIONS": "Certifications listed on the profile.",
    "COMPANY_FOLLOWS": "Companies and other entities the member follows.",
    "CONNECTIONS": "First-degree connections: name, profile URL, company, position, date.",
    "CONTACTS": "Contacts imported into LinkedIn.",
    "COURSES": "Courses listed on the profile.",
    "EASYAPPLY_BLOCKING": "Account records for job applications on third-party systems.",
    "EDUCATION": "Schools listed on the profile.",
    "EMAIL_ADDRESSES": "Email addresses associated with the account, past and present.",
    "ENDORSEMENTS": "Skill endorsements given and received.",
    "Events": "Events attended, declined, or requested to attend.",
    "GROUPS": "LinkedIn groups the member belongs to.",
    "HONORS": "Honors listed on the profile.",
    "IDENTITY_CREDENTIALS_AND_ASSETS": "Private identity assets and credentials.",
    "INBOX": "Messages sent and received.",
    "INFERENCE_TAKEOUT": "Inferences about the member based on profile and activity.",
    "INSTANT_REPOSTS": "Reposts with date, time and link.",
    "INVITATIONS": "Connection invitations sent and received.",
    "JOB_APPLICANT_SAVED_ANSWERS": "Saved answers to basic job application questions.",
    "JOB_APPLICATIONS": "Jobs the member applied to.",
    "JOB_POSTINGS": "Jobs the member posted.",
    "JOB_SEEKER_PREFERENCES": "Job search preferences.",
    "LANGUAGES": "Languages and proficiency listed on the profile.",
    "LEARNING": "LinkedIn Learning content the member watched or saved.",
    "LEARNING_COACH_AI_TAKEOUT": "Conversations with the LinkedIn Learning coach chatbot.",
    "LEARNING_COACH_INBOX": "Conversations with the LinkedIn Learning coach chatbot.",
    "LEARNING_ROLEPLAY_INBOX": "Feedback from LinkedIn Learning role-play scenarios.",
    "LOGIN": "Stored account logins.",
    "MARKETPLACE_ENGAGEMENTS": "Services Marketplace engagements.",
    "MARKETPLACE_OPPORTUNITIES": "Services the member is looking for on Services Marketplace.",
    "MARKETPLACE_PROVIDERS": "Services the member provides on Services Marketplace.",
    "MEMBER_FOLLOWING": "People the member follows.",
    "MEMBER_SHARE_INFO": "Posts and reposts: date, URL, text and visibility.",
    "ORGANIZATIONS": "Organizations listed on the profile.",
    "PATENTS": "Patents listed on the profile.",
    "PHONE_NUMBERS": "Phone numbers linked to the account.",
    "POSITIONS": "Job positions listed on the profile.",
    "PREMIUM_NOTES": "Private notes about connections.",
    "PROFILE": "Basic profile information: name, headline, summary, location.",
    "PROFILE_SUMMARY": "AI-generated profile summary.",
    "PROJECTS": "Projects listed on the profile.",
    "PUBLICATIONS": "Publications listed on the profile.",
    "RECEIPTS": "Purchases associated with the account.",
    "RECEIPTS_LBP": "Purchases of LinkedIn services.",
    "RECOMMENDATIONS": "Recommendations given and received.",
    "REGISTRATION": "Date the member joined LinkedIn.",
    "REVIEWS": "Ratings and reviews the member provided.",
    "RICH_MEDIA": "URLs of photos, videos and documents the member shared.",
    "SAVED_JOB_ALERTS": "Saved job alerts.",
    "SAVED_JOBS": "Saved jobs.",
    "SEARCHES": "Recent searches.",
    "SECURITY_CHALLENGE_PIPE": "Sign-in security challenges.",
    "SKILLS": "Skills listed on the profile.",
    "TALENT_QUESTION_SAVED_RESPONSE": "Saved answers to job poster questions.",
    "TEST_SCORES": "Test scores listed on the profile.",
    "TRUSTED_GRAPH": "Identity, workplace and education verifications.",
    "VOLUNTEERING_EXPERIENCES": "Volunteering experience.",
    "WHATSAPP_NUMBERS": "WhatsApp numbers linked to the account (undocumented domain).",
}


def describe_domain(domain: str) -> str:
    """Return the documented description of a snapshot domain.

    Args:
        domain: Snapshot domain name.

    Returns:
        The description, or "" for an unknown domain.
    """
    return DOMAIN_DESCRIPTIONS.get(domain, "")
