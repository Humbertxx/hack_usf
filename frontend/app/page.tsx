"use client";

import Image from "next/image";
import { useContext, useState } from "react";
import { OldPeopleContext, useOldPeopleContext } from "./OldPeopleContext";

export default function Home() {
  // 1 for grandma, 2 for grandpa, 3 for both
  const { oldPeople, setOldPeople } = useOldPeopleContext();

  const grandpa = () => {
    if (oldPeople === 2) {
      setOldPeople(0);
    } else if (oldPeople === 1) {
      setOldPeople(3);
    } else if (oldPeople === 3) {
      setOldPeople(1);
    } else {
      setOldPeople(2);
    }
  };

  const grandma = () => {
    if (oldPeople === 1) {
      setOldPeople(0);
    } else if (oldPeople === 2) {
      setOldPeople(3);
    } else if (oldPeople === 3) {
      setOldPeople(2);
    } else {
      setOldPeople(1);
    }
  };

  return (
    <>
      <div className="flex flex-col items-center justify-center w-screen mt-10 gap-5">
        <p className="font-bold text-lg md:text-xl lg:text-3xl">
          Welcome to Enrollment! Choose family members to enroll below.
        </p>
        <Image
          src="/oldpeople.jpg"
          alt="Family"
          width={400}
          height={400}
          className="w-[400px] h-[400px] object-cover rounded-2xl shadow"
        />
        <div className="shadow flex justify-center items-center bg-sky-50 rounded-2xl w-[300px] h-[50px]">
          <button
            onClick={() => grandma()}
            className={`hover:shadow bg-sky-50 w-[50%] h-full rounded-l-2xl hover:scale-110 transition duration-100 ease-in ${oldPeople === 1 || oldPeople === 3 ? "bg-sky-200" : ""}`}
          >
            grandma
          </button>
          <button
            onClick={() => grandpa()}
            className={`hover:shadow bg-sky-50 w-[50%] h-full rounded-r-2xl hover:scale-110 transition duration-100 ease-in ${oldPeople === 2 || oldPeople === 3 ? "bg-sky-200" : ""}`}
          >
            grandpa
          </button>
        </div>
        <div className="flex items-center justify-center gap-5">
          {oldPeople === 0 && (
            <div className="bg-sky-50 p-5 rounded-lg shadow">
              <p className="font-bold text-lg">No One Selected!</p>
            </div>
          )}
          {oldPeople === 1 && (
            <button className="bg-sky-50 p-5 rounded-lg shadow hover:scale-110 transition duration-100 ease-in">
              <p className="font-bold text-lg">Select Grandma</p>
            </button>
          )}
          {oldPeople === 2 && (
            <button className="bg-sky-50 p-5 rounded-lg shadow hover:scale-110 transition duration-100 ease-in">
              <p className="font-bold text-lg">Select Grandpa</p>
            </button>
          )}
          {oldPeople === 3 && (
            <button className="bg-sky-50 p-5 rounded-lg shadow hover:scale-110 transition duration-100 ease-in">
              <p className="font-bold text-lg">Select Grandparents</p>
            </button>
          )}
        </div>
      </div>
    </>
  );
}
