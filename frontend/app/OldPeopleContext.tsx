"use client";

import { useContext, createContext, useState, ReactNode } from "react";

// 1. Define the shape of your context data
interface OldPeopleContextType {
  oldPeople: number;
  setOldPeople: (value: number) => void;
  Navbar: boolean;
  setNavbar: (value: boolean) => void;
}

// 2. Pass the type to createContext and provide 'undefined' as the default argument
export const OldPeopleContext = createContext<OldPeopleContextType | undefined>(
  undefined,
);

// 3. Define the props for your provider
interface ProviderProps {
  children: ReactNode;
}

export const useOldPeopleContext = () => {
  const context = useContext(OldPeopleContext);
  if (!context) {
    throw new Error(
      "useOldPeopleContext must be used within an OldPeopleProvider",
    );
  }
  return context;
};

export const OldPeopleProvider = ({ children }: ProviderProps) => {
  const [oldPeople, setOldPeople] = useState<number>(0);
  const [Navbar, setNavbar] = useState<boolean>(true);
  return (
    <OldPeopleContext.Provider
      value={{ oldPeople, setOldPeople, Navbar, setNavbar }}
    >
      {children}
    </OldPeopleContext.Provider>
  );
};
