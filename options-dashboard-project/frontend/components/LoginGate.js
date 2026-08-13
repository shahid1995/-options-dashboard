import Centered from "@/components/Centered";
import { C } from "@/lib/theme";

// Returns a full-page placeholder while login status is unknown or the user
// is logged out; returns null once logged in so the page can render.
export function loginGateFor(loggedIn) {
  if (loggedIn === null) return <Centered>Checking login…</Centered>;
  if (loggedIn === false)
    return (
      <Centered>
        Not logged in.{" "}
        <a href="/" style={{ color: C.gold }}>
          Go back and log in
        </a>
        .
      </Centered>
    );
  return null;
}
