# Discussion Ban/Unban API Documentation

This document describes the ban and unban API endpoints for managing user access to discussion forums.

## API Endpoints

All endpoints are available under both `/api/v1/` and `/api/v2/` prefixes.

---

## 1. Ban a User

**Endpoint:** `POST /api/v2/users/bans`

Bans a user from discussions at either course or organization level.

### Request Body

```json
{
  "user_id": "123",
  "banned_by_id": "456",
  "scope": "course",
  "course_id": "course-v1:edX+DemoX+Demo_Course",
  "reason": "Posting spam content"
}
```

#### Required Fields
- `user_id` (string): ID of the user to ban
- `banned_by_id` (string): ID of the moderator performing the ban
- `scope` (string): Either `"course"` or `"organization"`

#### Conditional Fields
- `course_id` (string): **Required** when `scope="course"`
- `org_key` (string): **Required** when `scope="organization"`
- `reason` (string): Optional reason for the ban

### Course-Level Ban Example

```json
{
  "user_id": "123",
  "banned_by_id": "456",
  "scope": "course",
  "course_id": "course-v1:edX+DemoX+Demo_Course",
  "reason": "Violating discussion guidelines"
}
```

### Organization-Level Ban Example

```json
{
  "user_id": "123",
  "banned_by_id": "456",
  "scope": "organization",
  "org_key": "edX",
  "reason": "Repeated violations across multiple courses"
}
```

### Success Response (201 Created)

```json
{
  "id": 1,
  "user": {
    "id": 123,
    "username": "learner",
    "email": "learner@example.com"
  },
  "course_id": "course-v1:edX+DemoX+Demo_Course",
  "org_key": "edX",
  "scope": "course",
  "reason": "Posting spam content",
  "is_active": true,
  "banned_at": "2024-01-15T10:30:00Z",
  "banned_by": {
    "id": 456,
    "username": "moderator"
  },
  "unbanned_at": null,
  "unbanned_by": null
}
```

### Error Responses

**400 Bad Request** - Invalid parameters
```json
{
  "error": "course_id is required for course-level bans"
}
```

**404 Not Found** - User not found
```json
{
  "error": "User not found"
}
```

**500 Internal Server Error** - Server error
```json
{
  "error": "Failed to ban user"
}
```

---

## 2. Unban a User

**Endpoint:** `POST /api/v2/users/bans/<ban_id>/unban`

Unbans a user from discussions. The behavior depends on the ban scope:
- **Course-level ban**: Completely removes the ban
- **Organization-level ban without course_id**: Completely removes the org ban
- **Organization-level ban with course_id**: Creates an exception for that specific course

### Request Body

```json
{
  "unbanned_by_id": "456",
  "course_id": "course-v1:edX+DemoX+Demo_Course",
  "reason": "User appeal approved"
}
```

#### Required Fields
- `unbanned_by_id` (string): ID of the moderator performing the unban

#### Optional Fields
- `course_id` (string): When provided for an org-level ban, creates a course-specific exception
- `reason` (string): Optional reason for unbanning

### Complete Unban Example

```json
{
  "unbanned_by_id": "456",
  "reason": "User appeal approved"
}
```

### Course Exception to Org Ban Example

For an organization-level ban, you can unban for a specific course while keeping the org ban active:

```json
{
  "unbanned_by_id": "456",
  "course_id": "course-v1:edX+DemoX+Demo_Course",
  "reason": "Approved for this specific course"
}
```

### Success Response (200 OK)

**Complete Unban:**
```json
{
  "status": "success",
  "message": "User learner unbanned successfully",
  "exception_created": false,
  "ban": {
    "id": 1,
    "user": {
      "id": 123,
      "username": "learner",
      "email": "learner@example.com"
    },
    "course_id": "course-v1:edX+DemoX+Demo_Course",
    "org_key": "edX",
    "scope": "course",
    "reason": "Posting spam content",
    "is_active": false,
    "banned_at": "2024-01-15T10:30:00Z",
    "banned_by": {
      "id": 456,
      "username": "moderator"
    },
    "unbanned_at": "2024-01-16T14:20:00Z",
    "unbanned_by": {
      "id": 456,
      "username": "moderator"
    }
  },
  "exception": null
}
```

**Course Exception (Org Ban Still Active):**
```json
{
  "status": "success",
  "message": "User learner unbanned from course-v1:edX+DemoX+Demo_Course (org-level ban still active for other courses)",
  "exception_created": true,
  "ban": {
    "id": 1,
    "user": {
      "id": 123,
      "username": "learner",
      "email": "learner@example.com"
    },
    "course_id": null,
    "org_key": "edX",
    "scope": "organization",
    "reason": "Repeated violations",
    "is_active": true,
    "banned_at": "2024-01-15T10:30:00Z",
    "banned_by": {
      "id": 456,
      "username": "moderator"
    },
    "unbanned_at": null,
    "unbanned_by": null
  },
  "exception": {
    "id": 5,
    "ban_id": 1,
    "course_id": "course-v1:edX+DemoX+Demo_Course",
    "unbanned_by": "moderator",
    "reason": "Approved for this specific course",
    "created_at": "2024-01-16T14:20:00Z"
  }
}
```

### Error Responses

**404 Not Found** - Ban not found
```json
{
  "error": "Active ban with id 999 not found"
}
```

**404 Not Found** - Moderator not found
```json
{
  "error": "Moderator user not found"
}
```

**500 Internal Server Error** - Server error
```json
{
  "error": "Failed to unban user"
}
```

---

## 3. List Banned Users

**Endpoint:** `GET /api/v2/users/banned`

Retrieves a list of banned users with optional filtering.

### Query Parameters

- `course_id` (optional): Filter by course ID
- `org_key` (optional): Filter by organization key
- `include_inactive` (optional): Include inactive/unbanned users (default: false)

### Examples

**Get all active bans:**
```
GET /api/v2/users/banned
```

**Get bans for a specific course:**
```
GET /api/v2/users/banned?course_id=course-v1:edX+DemoX+Demo_Course
```

**Get bans for an organization:**
```
GET /api/v2/users/banned?org_key=edX
```

**Include inactive bans:**
```
GET /api/v2/users/banned?course_id=course-v1:edX+DemoX+Demo_Course&include_inactive=true
```

### Success Response (200 OK)

```json
[
  {
    "id": 1,
    "user": {
      "id": 123,
      "username": "learner1",
      "email": "learner1@example.com"
    },
    "course_id": "course-v1:edX+DemoX+Demo_Course",
    "org_key": "edX",
    "scope": "course",
    "reason": "Posting spam content",
    "is_active": true,
    "banned_at": "2024-01-15T10:30:00Z",
    "banned_by": {
      "id": 456,
      "username": "moderator"
    },
    "unbanned_at": null,
    "unbanned_by": null
  },
  {
    "id": 2,
    "user": {
      "id": 124,
      "username": "learner2",
      "email": "learner2@example.com"
    },
    "course_id": null,
    "org_key": "edX",
    "scope": "organization",
    "reason": "Repeated violations",
    "is_active": true,
    "banned_at": "2024-01-14T09:15:00Z",
    "banned_by": {
      "id": 456,
      "username": "moderator"
    },
    "unbanned_at": null,
    "unbanned_by": null
  }
]
```

### Error Responses

**400 Bad Request** - Invalid query parameters
```json
{
  "error": "Invalid course_id format"
}
```

**500 Internal Server Error** - Server error
```json
{
  "error": "Failed to fetch banned users"
}
```

---

## 4. Get Ban Details

**Endpoint:** `GET /api/v2/users/bans/<ban_id>`

Retrieves details of a specific ban.

### Path Parameters

- `ban_id` (integer): The ID of the ban

### Example

```
GET /api/v2/users/bans/1
```

### Success Response (200 OK)

```json
{
  "id": 1,
  "user": {
    "id": 123,
    "username": "learner",
    "email": "learner@example.com"
  },
  "course_id": "course-v1:edX+DemoX+Demo_Course",
  "org_key": "edX",
  "scope": "course",
  "reason": "Posting spam content",
  "is_active": true,
  "banned_at": "2024-01-15T10:30:00Z",
  "banned_by": {
    "id": 456,
    "username": "moderator"
  },
  "unbanned_at": null,
  "unbanned_by": null
}
```

### Error Responses

**404 Not Found** - Ban not found
```json
{
  "error": "Ban with id 999 not found"
}
```

**500 Internal Server Error** - Server error
```json
{
  "error": "Failed to fetch ban details"
}
```

---

## Use Cases

### 1. Ban User from a Course

When a moderator clicks "Ban user in this course" from the discussion UI:

```bash
curl -X POST http://localhost:4567/api/v2/users/bans \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "123",
    "banned_by_id": "456",
    "scope": "course",
    "course_id": "course-v1:edX+DemoX+Demo_Course",
    "reason": "Violating discussion guidelines"
  }'
```

### 2. Ban User from Organization

When a moderator clicks "Ban user in this organization":

```bash
curl -X POST http://localhost:4567/api/v2/users/bans \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "123",
    "banned_by_id": "456",
    "scope": "organization",
    "org_key": "edX",
    "reason": "Repeated violations across multiple courses"
  }'
```

### 3. Unban User from Course

When a moderator clicks "Unban this user?" for a course-level ban:

```bash
curl -X POST http://localhost:4567/api/v2/users/bans/1/unban \
  -H "Content-Type: application/json" \
  -d '{
    "unbanned_by_id": "456",
    "reason": "User appeal approved"
  }'
```

### 4. Unban User from Organization

Complete removal of organization-level ban:

```bash
curl -X POST http://localhost:4567/api/v2/users/bans/2/unban \
  -H "Content-Type: application/json" \
  -d '{
    "unbanned_by_id": "456",
    "reason": "Ban period expired"
  }'
```

### 5. Create Course Exception to Org Ban

Allow user in specific course while keeping org ban active:

```bash
curl -X POST http://localhost:4567/api/v2/users/bans/2/unban \
  -H "Content-Type: application/json" \
  -d '{
    "unbanned_by_id": "456",
    "course_id": "course-v1:edX+DemoX+Demo_Course",
    "reason": "Approved for this specific course after appeal"
  }'
```

### 6. List All Banned Users in a Course

```bash
curl -X GET "http://localhost:4567/api/v2/users/banned?course_id=course-v1:edX+DemoX+Demo_Course"
```

---

## Important Notes

1. **Scope Hierarchy**: Organization-level bans apply to all courses within that organization unless a course-specific exception is created.

2. **Ban Reactivation**: If you ban a user who was previously unbanned, the old ban record is reactivated with new timestamps and reason.

3. **Denormalization**: Course-level bans store the `org_key` extracted from the `course_id` for easier querying.

4. **Audit Trail**: All ban/unban actions are logged in `DiscussionModerationLog` for audit purposes.

5. **Soft Delete**: Bans are not deleted but marked as `is_active=false` when unbanned, preserving history.

6. **Exception Model**: Course exceptions to organization bans use the `DiscussionBanException` model.

---

## Frontend Integration

The UI shown in the screenshots should:

1. **Display context menu** with "Ban" option showing submenu:
   - "Ban user in this course"
   - "Ban user in this organization"

2. **Show confirmation dialog** with appropriate message:
   - Course: "Are you sure you want to ban {username} from discussions in this course?"
   - Organization: "Are you sure you want to ban {username} from discussions across this organization?"

3. **For unbanning**, show "Unban" option in menu for banned users with submenu:
   - "Unban user from discussions in this course"
   - "Unban user from discussions in this organization"

4. **Display confirmation** with appropriate message based on context

5. **Handle responses** showing success/error messages to the user

6. **Refresh UI** to hide banned user's content or show appropriate indicators
