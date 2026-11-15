// NEXT CODE
// src/hooks/useAIStateEvents.jsx

import { useEffect } from "react";
import { useAIState } from "../context/useAIState";

export default function useAIStateEvents() {
  const { setAIState } = useAIState();

  useEffect(() => {
    const handleState = (event) => {
      if (!event.detail) return;

      setAIState(event.detail);
    };

    window.addEventListener(
      "mayday:state",
      handleState
    );

    return () => {
      window.removeEventListener(
        "mayday:state",
        handleState
      );
    };
  }, [setAIState]);
}