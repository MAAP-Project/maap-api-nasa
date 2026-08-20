STATUS_ACTIVE = 'active'
# Newly registered members start here (no admin review yet). Only STATUS_ACTIVE
# grants API access; pending/inactive/declined all deny (deny-by-default).
STATUS_PENDING = 'pending'
STATUS_INACTIVE = 'inactive'
STATUS_DECLINED = 'declined'
# Legacy value, superseded by the four above. Retained so tokens/rows created
# before the expanded status model still resolve; treated as inactive.
STATUS_SUSPENDED = 'suspended'

# The admin-selectable status values (excludes the legacy 'suspended').
MEMBER_STATUSES = [STATUS_PENDING, STATUS_ACTIVE, STATUS_INACTIVE, STATUS_DECLINED]
