import { ReviewSkeleton } from "@/components/ReviewSkeleton";
import { TopBar } from "@/components/TopBar";

export function ReviewPending() {
  return (
    <>
      <TopBar processing />
      <ReviewSkeleton />
    </>
  );
}
