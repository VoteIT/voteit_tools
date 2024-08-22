def get_user(value: str, meeting):
    try:
        return meeting.participants.get(**{"pk": int(value)})
    except ValueError:
        return meeting.participants.get(**{"userid": value})


def get_group(value: str, meeting):
    try:
        return meeting.groups.get(**{"pk": int(value)})
    except ValueError:
        return meeting.groups.get(**{"groupid": value})
