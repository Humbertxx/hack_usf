import Image from "next/image";
import InsightCard from "../components/InsightCard";

export default function Home() {

  return( 
  <>
  <div className="px-3">
    <h1 className="mt-4 text-3xl font-bold text-black">Health Insights</h1>
    <p className="mt-0 text-base text-gray-600">AI-powered analysis of weekly pattern and trends</p>
  </div>

  <div>
    <InsightCard />
  </div>
  </>
  );
}
