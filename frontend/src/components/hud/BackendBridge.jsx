import { useEffect } from "react";
import { processCommand } from "../../services/api";
import { useAIState } from "../../context/useAIState";

export default function BackendBridge() {
  const { setAIState } = useAIState();

  useEffect(() => {
    let mounted = true;

    // Show the full text on screen, but let MAYDAY speak a shorter version.
    const emitResponse = (text, spoken) => {
      window.dispatchEvent(
        new CustomEvent("mayday:response", {
          detail: text,
        }),
      );

      window.dispatchEvent(
        new CustomEvent("mayday:speak", {
          detail: spoken || text,
        }),
      );
    };

    const handleCommand = async (event) => {
      const command = String(event.detail || "").trim();

      if (!command) {
        return;
      }

      if (mounted) {
        setAIState("THINKING");
      }

      try {
        const result = await processCommand(command);

        if (!mounted) {
          return;
        }

        if (!result || !result.success) {
          setAIState("IDLE");

          emitResponse(
            result?.error || "MAYDAY backend connection failed.",
          );

          return;
        }

        const data = result.data;

        if (!data) {
          setAIState("IDLE");

          emitResponse("MAYDAY received an empty backend response.");

          return;
        }

        const response =
          data.response ||
          data.message ||
          "Command completed.";

        if (data.state === "IDLE") {
          setAIState("IDLE");
        } else if (data.state === "THINKING") {
          setAIState("THINKING");
        } else {
          setAIState("RESPONDING");
        }

        emitResponse(response, data.spoken);
      } catch (error) {
        if (!mounted) {
          return;
        }

        setAIState("IDLE");

        emitResponse(`Backend error: ${error.message}`);
      }
    };

    window.addEventListener(
      "mayday:command",
      handleCommand,
    );

    return () => {
      mounted = false;

      window.removeEventListener(
        "mayday:command",
        handleCommand,
      );
    };
  }, [setAIState]);

  return null;
}
