# scope

The checker does not know whose text it is looking at.

- `check-draft` inspects the file it is given. Any draft, including one written by someone else.
- `check-own-posts` fetches the numeric id it is given, for any account the token can read.

Default, unless the user was explicit:

1. Check the operator's own draft before posting. That is `check-draft`.
2. Review already-posted items only for the operator's own account id.
3. Do not collect other accounts, fill the corpus from other people, or go looking for a group of accounts that share a code.

If the user pastes one draft and asks for a check, check that draft and stop. If the user names one account id and asks for a review of that account, you may run `monitor` on that id and stop. Do not expand to followers, replies, or accounts that look similar.
