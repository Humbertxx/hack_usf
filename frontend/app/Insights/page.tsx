import Image from "next/image";
import InsightCard from "../components/InsightCard";

export default function Home() {
  return (
    <>
      <div className="p-10 w-full h-full flex flex-col gap-10 items-center justify-start">
        <div className="flex justify-between w-[90%] md:w-[80%]">
          <div className="flex flex-col gap-3">
            <h1 className="m-0 text-3xl font-bold text-black">
              Health Insights
            </h1>
            <p className="mt-0 text-sm text-gray-600">
              AI-powered analysis of weekly pattern and trends
            </p>
          </div>
        </div>
        <div className="flex justify-start gap-5 [90%] md:w-[80%]">
          <InsightCard />
        </div>
      </div>
    </>
  );
}
