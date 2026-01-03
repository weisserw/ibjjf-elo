import React from "react";

export const AppContext = React.createContext({});
export const useAppContext = () => React.useContext(AppContext);
