import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { registerServiceWorker } from "./lib/serviceWorkerRegistration.js";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

registerServiceWorker();
