using System;
using System.IO;
using System.Threading;
using Windows.Foundation;
using Windows.Management.Deployment;

namespace msixinstall
{
    /// <summary>
    /// Installs the RETextRecBench MSIX from the interactive session with no window at all
    /// (Shivam's headless rule, machines/HP_LAPTOP.md): Add-AppxPackage fails with 0x80070005 over
    /// SSH and from an S4U task because the AppX Deployment PLM needs the logged-on session, and a
    /// console program in that session could show a window. GUI subsystem + no UI = nothing on
    /// screen. Usage: msixinstall.exe &lt;package.msix&gt; &lt;result.txt&gt;
    /// </summary>
    internal static class Program
    {
        private static int Main(string[] args)
        {
            if (args.Length < 2)
            {
                return 2;
            }
            string msix = args[0];
            string result = args[1];
            string text;
            try
            {
                var manager = new PackageManager();
                IAsyncOperationWithProgress<DeploymentResult, DeploymentProgress> op =
                    manager.AddPackageAsync(new Uri(msix), null, DeploymentOptions.ForceUpdateFromAnyVersion);
                DateTime deadline = DateTime.UtcNow.AddMinutes(10);
                while (op.Status == AsyncStatus.Started && DateTime.UtcNow < deadline)
                {
                    Thread.Sleep(200);
                }
                text = "status=" + op.Status;
                if (op.Status == AsyncStatus.Completed)
                {
                    DeploymentResult done = op.GetResults();
                    text += Environment.NewLine + "add=ok: " + done.ExtendedErrorCode;
                }
                else if (op.Status == AsyncStatus.Error)
                {
                    text += Environment.NewLine + "add=failed: 0x" + op.ErrorCode.HResult.ToString("X8")
                            + " " + op.ErrorCode.Message;
                }
                else
                {
                    text += Environment.NewLine + "add=timeout";
                }
            }
            catch (Exception ex)
            {
                text = "add=exception: " + ex.GetType().Name + ": " + ex.Message;
            }
            File.WriteAllText(result, text);
            return 0;
        }
    }
}
