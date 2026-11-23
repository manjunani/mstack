import { Link } from "react-router-dom";

export function Login({ failed }) {
  return (
    <form onSubmit={() => {}}>
      <h1>Welcome</h1>
      <label htmlFor="name">Name</label>
      <input id="name" placeholder="Your name here" />
      {failed && <p className="form-error error">Could not save.</p>}
      <button type="submit">Sign in</button>
      <button type="button">Click here</button>
      {/* <button>Old hidden label</button> */}
      <Link to="/login">Log in</Link>
      <a href="/help">Get help with signing in</a>
    </form>
  );
}
